from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable


def install() -> types.ModuleType:
    """Install a small VIKTOR-compatible test stub when the SDK is unavailable."""

    existing = sys.modules.get("viktor")
    if existing is not None:
        return existing

    viktor = types.ModuleType("viktor")

    class ExecutionError(RuntimeError):
        pass

    class WorkerSessionError(RuntimeError):
        pass

    class WorkerSessionAttachError(WorkerSessionError):
        def __init__(self, message: str = "attach failed", reason: str | None = None):
            super().__init__(message)
            self.reason = reason

    class UserError(RuntimeError):
        pass

    errors = types.SimpleNamespace(
        ExecutionError=ExecutionError,
        WorkerSessionError=WorkerSessionError,
        WorkerSessionAttachError=WorkerSessionAttachError,
    )

    class _Field:
        def __init__(self, *args: Any, **kwargs: Any):
            self.args = args
            self.kwargs = kwargs
            self.default = kwargs.get("default")

    class Text(_Field):
        pass

    class TextField(_Field):
        pass

    class NumberField(_Field):
        pass

    class IntegerField(_Field):
        pass

    class BooleanField(_Field):
        pass

    class OptionField(_Field):
        pass

    class AutocompleteField(_Field):
        pass

    class LineBreak(_Field):
        pass

    class Table(_Field):
        pass

    class SetParamsButton(_Field):
        pass

    class ActionButton(_Field):
        pass

    class Parametrization:
        def __init__(self, width: int | None = None):
            self.width = width

    class Controller:
        pass

    def _view_decorator(*decorator_args: Any, **decorator_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
            function._viktor_view_args = decorator_args  # type: ignore[attr-defined]
            function._viktor_view_kwargs = decorator_kwargs  # type: ignore[attr-defined]
            return function

        return decorate

    class TableView:
        def __new__(cls, *args: Any, **kwargs: Any):
            return _view_decorator(*args, **kwargs)

    class PlotlyView:
        def __new__(cls, *args: Any, **kwargs: Any):
            return _view_decorator(*args, **kwargs)

    @dataclass
    class SetParamsResult:
        params: dict[str, Any]

        def get(self, key: str, default: Any = None) -> Any:
            return self.params.get(key, default)

    class TableResult:
        def __init__(
            self,
            data: list[list[Any]],
            *,
            column_headers: list[str] | tuple[str, ...] | None = None,
            row_headers: list[str] | tuple[str, ...] | None = None,
            enable_sorting_and_filtering: bool | None = None,
            enable_column_autosizing: bool = False,
            show_index: bool = True,
            index_header: str | None = None,
        ):
            self.data = data
            self.column_headers = list(column_headers or [])
            self.row_headers = list(row_headers or [])
            self.enable_sorting_and_filtering = enable_sorting_and_filtering
            self.enable_column_autosizing = enable_column_autosizing
            self.show_index = show_index
            self.index_header = index_header

    @dataclass
    class PlotlyResult:
        figure: Any

    class _EUnits:
        kN_m_C = 6

    class _EItemTypeElm:
        ObjectElm = 0
        Element = 1
        GroupElm = 2
        SelectionElm = 3

    @contextmanager
    def _unconfigured_attach(*args: Any, **kwargs: Any):
        del args, kwargs
        raise WorkerSessionAttachError(reason="error_attach_no_instance")
        yield None

    etabs = types.SimpleNamespace(
        eUnits=_EUnits,
        eItemTypeElm=_EItemTypeElm,
        attach=_unconfigured_attach,
    )
    autocad = types.SimpleNamespace(attach=_unconfigured_attach)

    for name, value in {
        "ExecutionError": ExecutionError,
        "WorkerSessionError": WorkerSessionError,
        "WorkerSessionAttachError": WorkerSessionAttachError,
        "UserError": UserError,
        "errors": errors,
        "Text": Text,
        "TextField": TextField,
        "NumberField": NumberField,
        "IntegerField": IntegerField,
        "BooleanField": BooleanField,
        "OptionField": OptionField,
        "AutocompleteField": AutocompleteField,
        "LineBreak": LineBreak,
        "Table": Table,
        "SetParamsButton": SetParamsButton,
        "ActionButton": ActionButton,
        "Parametrization": Parametrization,
        "Controller": Controller,
        "TableView": TableView,
        "PlotlyView": PlotlyView,
        "SetParamsResult": SetParamsResult,
        "TableResult": TableResult,
        "PlotlyResult": PlotlyResult,
        "etabs": etabs,
        "autocad": autocad,
    }.items():
        setattr(viktor, name, value)

    external = types.ModuleType("viktor.external")
    external_autocad = types.ModuleType("viktor.external.autocad")

    class AcRegenType:
        acAllViewports = 1

    external_autocad.AcRegenType = AcRegenType
    external.autocad = external_autocad

    sys.modules["viktor"] = viktor
    sys.modules["viktor.external"] = external
    sys.modules["viktor.external.autocad"] = external_autocad
    return viktor
