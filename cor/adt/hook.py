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


def mark_hook(target: Target):
    def mark(fn):
        fn.hook_target = target
        return fn
    return mark


def field_invariant(fn: typing.Callable):
    '''create record field invariant factory

    The hook function is called after all record fields are initialized. Hook
    gets (initialized_record_instance, corresponding_field_name,
    corresponding_field_value) as parameters and should raise exception if
    invariant check is failed.

    '''
    def create_invariant(field_name):
        @functools.wraps(fn)
        @mark_hook(Target.PostInit)
        def wrapper(obj):
            try:
                return fn(obj, field_name, getattr(obj, field_name, None))
            except Exception as err:
                raise error.InvalidFieldError(field_name, "Failed invariant check") from err

        return wrapper

    return HooksFactory(None, create_invariant)
