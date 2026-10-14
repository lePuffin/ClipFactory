"""Errors exposed by Content Profile persistence."""


class ProfileNotFound(LookupError):
    pass


class ProfileNameConflict(ValueError):
    pass


class ActiveProfileDeleteForbidden(ValueError):
    pass
