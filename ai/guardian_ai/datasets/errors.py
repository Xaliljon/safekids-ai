"""Dataset platform errors."""


class DatasetError(Exception):
    """Base class for dataset platform errors."""


class AnnotationError(DatasetError):
    """An annotation file or record is malformed."""


class TaxonomyError(DatasetError):
    """A label taxonomy is invalid."""


class DatasetValidationError(DatasetError):
    """A dataset manifest or structure is invalid."""


class DatasetRegistryError(DatasetError):
    """A dataset could not be found or verified in the registry."""


class DatasetPublishError(DatasetError):
    """A dataset failed the publish gates (quality/privacy) and was refused."""
