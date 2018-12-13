import abc
import enum
import functools
import typing

from . import error
from .operation import (
    default_conversion,
    get_contract_info,
    Operation,
)


class HooksFactory:
    def __init__(self, operation, *factories):
        self._operation = operation
        self._factories = factories

    @property
    def operation(self):
        return self._operation

    def gen_hooks(self, name):
        for create in self._factories:
            yield create(name)

    def extended(self, operation, factories):
        return HooksFactory(operation, *factories, *self._factories)

    def __lshift__(self, hooks):
        error.ensure_has_type(HooksFactory, hooks)
        return hooks.extended(self._operation, self._factories)

    def __rlshift__(self, operation: Operation):
        error.ensure_has_type(Operation, operation)
        return HooksFactory(operation, *self._factories)


@default_conversion.register(HooksFactory)
def default_conversion_reject_hooks(v):
    raise ValueError(get_contract_info(v))


class Target(enum.Enum):
    PostInit = '_hook_post_init'
    Init = '_hook_init'


def mark_hook(target: Target):
    def mark(fn):
        fn.hook_target = target
        return fn
    return mark


def field_hook(target: Target, hook_name: str, fn: typing.Callable):
    '''construct hook factory for the field called corresponding to the target

    Hook function has signature fn(instance, name, value) where:

    - instance is initialized record instance;

    - name - corresponding field name,

    - value - corresponding field value

    '''
    def create_invariant(field_name):
        @functools.wraps(fn)
        @mark_hook(target)
        def wrapper(obj):
            try:
                return fn(obj, field_name, getattr(obj, field_name, None))
            except Exception as err:
                raise error.InvalidFieldError(field_name, "Failed {} check".format(hook_name)) from err

        return wrapper

    return HooksFactory(None, create_invariant)


def field_invariant(fn: typing.Callable):
    '''create record field invariant factory

    Hook should raise exception if invariant check is failed.

    '''
    return field_hook(Target.PostInit, 'invariant', fn)


def field_aggregate(fn: typing.Callable):
    '''create hook factory for the aggregate

    Fields are set not in the order of declaration - the reason why field can't
    use other field value as the input. Hook produced by this factory gives the
    way to set any field after all fields are set.

    Hook fn should return:

    - tuple (name, value) where name is the field name and value - new value for
    the field;

    - or None if field shouldn't be set.

    So, the hook can return any name and set any field of the instance but it
    should be used with caution: too relaxed usage can cause unexpected side
    effects.

    '''
    return field_hook(Target.Init, 'aggregate', fn)
