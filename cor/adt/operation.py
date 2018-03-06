import abc
import enum
import functools

from . import error


@functools.singledispatch
def as_basic_type(v):
    return v


class ContractInfo:
    '''Information about contract'''

    def __init__(self, info):
        self._get_info = info if callable(info) else lambda: info

    def __str__(self):
        return self.contract

    @property
    def contract(self):
        return self._get_info()


def set_contract_info(target, info):
    target._contract_info = ContractInfo(info)

@functools.singledispatch
def _obj_info(obj):
    return getattr(obj, '_contract_info', obj.__doc__ or repr(obj))


_obj_info.register(type)
def _obj_info_for_type(obj):
    return obj.__name__


_obj_info.register(enum.EnumMeta)
def _obj_info_for_enum(obj):
    return '{}({})'.format(obj.__name__, ', '.join('"{}"'.format(v.value) for v in obj))


class Operation(abc.ABC):
    def __and__(self, fn):
        return And(self, default_conversion(fn))

    def __or__(self, fn):
        return Or(self, default_conversion(fn))

    def _get_from_input(self, field_name, values):
        return values[field_name]

    @property
    @abc.abstractmethod
    def info(self):
        '''get operation contract info'''


_obj_info.register(Operation)
def _obj_info_for_operation(obj):
    return obj.info


@functools.singledispatch
def default_conversion(obj):
    return UnaryOperation(obj)


@default_conversion.register(type)
def default_conversion_for_type(obj):
    return expect_type(obj)


@default_conversion.register(Operation)
def default_conversion_for_operation(obj):
    return obj


class UnaryOperation(Operation):
    def __init__(self, convert):
        assert convert != self
        super().__init__()
        if isinstance(convert, Operation):
            assert isinstance(convert, UnaryOperation)
            self._convert = convert._convert
        else:
            self._convert = convert

    @property
    def info(self):
        res = _obj_info(self._convert)
        return str(res) if isinstance(res, ContractInfo) else 'convert to ' + res

    def prepare_field(self, field_name, values):
        res = self._construct_field(field_name, values)
        if res is None:
            raise error.MissingFieldError(field_name)
        return res

    def process_value(self, v):
        return self._convert(v)

    def _construct_field(self, field_name, values):
        try:
            input_data = self._get_from_input(field_name, values)
        except KeyError as err:
            return None
        except Exception as err:
            raise error.InvalidFieldError(field_name, _obj_info(err))

        try:
            return (field_name, self._convert(input_data))
        except error.Error:
            raise
        except Exception as err:
            raise error.InvalidFieldError(field_name, _obj_info(err)) from err


class BinaryOperation(Operation):
    def __init__(self, left, right):
        assert left != self
        assert right != self
        self._left = left
        self._right = right

    @property
    def info(self):
        return '{} {} {}'.format(
            _obj_info(self._left),
            self._operation_name,
            _obj_info(self._right)
        )



class And(BinaryOperation):
    _operation_name = 'and'

    def prepare_field(self, field_name, values):
        res = self._left.prepare_field(field_name, values)
        if res is None:
            return res

        name, value = res
        return self._right.prepare_field(field_name, {**values, name: value})


class Or(BinaryOperation):
    _operation_name = 'or'

    def prepare_field(self, field_name, values):
        try:
            res = self._left.prepare_field(field_name, values)
        except Exception as err_left:
            try:
                return self._right.prepare_field(field_name, values)
            except Exception as err_right:
                raise err_right from err_left
        else:
            return (
                self._right.prepare_field(field_name, values)
                if res is None
                else res
            )


def describe_contract(info):
    def decorator(fn):
        set_contract_info(fn, info)
        return fn
    return decorator


def convert(fn):
    return fn if isinstance(fn, Operation) else UnaryOperation(fn)


class Tag(enum.Enum):
    def __str__(self):
        return str(self.value)


@default_conversion.register(Tag)
def _(obj):
    return should_be(obj)


@as_basic_type.register(Tag)
def tag_as_basic_type(v):
    return v.value


class _SkipMissing(UnaryOperation):
    def __init__(self):
        @describe_contract('skip missing')
        def identity(v):
            return v

        super().__init__(identity)

    def prepare_field(self, field_name, values):
        return self._construct_field(field_name, values)


skip_missing = _SkipMissing()


class _ProvideMissing(UnaryOperation):
    def __init__(self, default_value):
        @describe_contract('provide {} if missing'.format(default_value))
        def replace_optional(v):
            return default_value if v is None else v

        super().__init__(replace_optional)

    def _get_from_input(self, field_name, values):
        value = values.get(field_name, None)
        return self._convert(value)


provide_missing = _ProvideMissing


def only_if(fn, info, err_cls=ValueError):
    cond = error.ensure_callable(fn)

    @describe_contract(lambda: 'accept only if ' + ContractInfo(info).contract)
    def convert_only_if(v):
        if not cond(v):
            raise err_cls({
                'info': "Value doesn't match condition",
                'condition': info or repr(fn),
                'value': v
            })
        return v

    return convert(convert_only_if)


def expect_types(*expected_types):
    assert expected_types
    type_names = [t.__name__ for t in expected_types]

    def has_expected_types(v):
        return isinstance(v, expected_types)

    info = (
        'has type {}'.format(type_names[0]) if len(type_names) == 1
        else 'has one of {} types'.format(type_names)
    )
    return only_if(has_expected_types, info, TypeError)


def expect_type(expected_type):
    return expect_types(expected_type)


def should_be(expected):
    def is_value(v):
        return v is expected

    return only_if(is_value, 'value is {} constant'.format(expected))


not_empty = only_if(bool, "not empty")


def choose_by_field(name, union_factories):
    assert(all(isinstance(cls, Factory) for cls in union_factories))

    def _get_choice_info():
        return 'or '.join(_obj_info(cls) for cls in union_factories)

    def _get_contract_info():
        return ('choose ({}) matching against'
                ' {} field to create one'.format(_get_choice_info(), name)
        )

    @describe_contract(_get_contract_info)
    def create(data):
        matched_cls = None
        for cls in union_factories:
            try:
                cls.prepare_field_from_input(name, data)
                matched_cls = cls
                break
            except Exception as err:
                continue
        if matched_cls is None:
            raise error.InvalidFieldError(
                name,
                "Can't find match for any of ({})".format(_get_choice_info())
            )

        return cls(data)

    return convert(create)


class FieldInvariant:
    def __init__(self, ensure_invariant):
        error.ensure_callable(ensure_invariant)
        self._ensure_invariant = ensure_invariant

    def check_field(self, record, field_name):
        try:
            self._ensure_invariant(record, field_name)
        except FieldError:
            raise
        except Exception as err:
            raise InvalidFieldError(field_name, err)
