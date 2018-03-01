
def ensure_callable(fn):
    if not callable(fn):
        raise TypeError({
            'info': "Contract should be callable",
            'value': fn,
            'type': type(fn)
        })
    return fn


def ensure_has_type(expected_types, v):
    if not isinstance(v, expected_types):
        raise TypeError({
            'info': "Value has unexpected type",
            'value': v,
            'actual': type(v),
            'expected': expected_types
        })
    return v


class Error(Exception):
    def __init__(self, name, info, **kwargs):
        super().__init__({'name': name, 'info': info, **kwargs})

    def wrap(self, name):
        return self._wrap(name, self)

    @classmethod
    def _wrap(cls, name, obj):
        return cls(name, obj)


class RecordError(Error):
    pass


class FieldError(Error):
    pass


class MissingFieldError(Error):
    def __init__(self, name, info='missing', **kwargs):
        super().__init__(name, info, **kwargs)


class InvalidFieldError(Error):
    pass


class AccessError(Exception):
    pass
