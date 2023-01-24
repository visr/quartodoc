from enum import Enum
from griffe.docstrings import dataclasses as ds
from griffe import dataclasses as dc
from dataclasses import dataclass
from tabulate import tabulate
from plum import dispatch
from typing import Tuple, Union


# Docstring rendering =========================================================

# utils -----------------------------------------------------------------------
# these largely re-format the output of griffe


def tuple_to_data(el: "tuple[ds.DocstringSectionKind, str]"):
    """Re-format funky tuple setup in example section to be a class."""
    assert len(el) == 2

    kind, value = el
    if kind.value == "examples":
        return ExampleCode(value)
    elif kind.value == "text":
        return ExampleText(value)

    raise ValueError(f"Unsupported first element in tuple: {kind}")


def docstring_section_narrow(el: ds.DocstringSection) -> ds.DocstringSection:
    # attempt to narrow down text sections
    prefix = "See Also\n---"
    if isinstance(el, ds.DocstringSectionText) and el.value.startswith(prefix):
        stripped = el.value.replace(prefix, "", 1).lstrip("-\n")
        return DocstringSectionSeeAlso(stripped, el.title)

    return el


class DocstringSectionKindPatched(Enum):
    see_also = "see also"


class DocstringSectionSeeAlso(ds.DocstringSection):
    kind = DocstringSectionKindPatched.see_also

    def __init__(self, value: str, title: "str | None"):
        self.value = value
        super().__init__(title)


@dataclass
class ExampleCode:
    value: str


@dataclass
class ExampleText:
    value: str


def escape(val: str):
    return f"`{val}`"


def sanitize(val: str):
    return val.replace("\n", " ")


# to_md -----------------------------------------------------------------------
# griffe function dataclass structure:
#   Object:
#     kind: Kind {"module", "class", "function", "attribute"}
#     name: str
#     docstring: Docstring
#     parent
#     path, canonical_path: str
#
#   Alias: wraps Object (_target) to lookup properties
#
#   Module, Class, Function, Attribute
#
# griffe docstring dataclass structure:
#   DocstringSection -> DocstringSection*
#   DocstringElement -> DocstringNamedElement -> Docstring*
#
#
# example templates:
#   https://github.com/mkdocstrings/python/tree/master/src/mkdocstrings_handlers/python/templates


class Renderer:
    style: str
    _registry: "dict[str, Renderer]" = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if cls.style in cls._registry:
            raise KeyError(f"A builder for style {cls.style} already exists")

        cls._registry[cls.style] = cls

    @classmethod
    def from_config(cls, cfg: "dict | Renderer | str"):
        if isinstance(cfg, Renderer):
            return cfg
        elif isinstance(cfg, str):
            style, cfg = cfg, {}
        elif isinstance(cfg, dict):
            style = cfg["style"]
            cfg = {k: v for k, v in cfg.items() if k != "style"}
        else:
            raise TypeError(type(cfg))

        if style.endswith(".py"):
            import importlib

            mod = importlib.import_module(style.rsplit(".", 1)[0])
            return mod.Renderer(**cfg)

        subclass = cls._registry[style]
        return subclass(**cfg)


class MdRenderer(Renderer):
    """Render docstrings to markdown.

    Parameters
    ----------
    header_level: int
        The level of the header (e.g. 1 is the biggest).
    show_signature: bool
        Whether to show the function signature.

    Examples
    --------

    >>> from quartodoc import MdRenderer, get_object
    >>> renderer = MdRenderer(header_level=2)
    >>> f = get_object("quartodoc", "get_object")
    >>> print(renderer.to_md(f)[:81])
    ## get_object
    `get_object(module: str, object_name: str, parser: str = 'numpy')`

    """

    style = "markdown"

    def __init__(
        self, header_level: int = 2, show_signature: bool = True, hook_pre=None
    ):
        self.header_level = header_level
        self.show_signature = show_signature
        self.hook_pre = hook_pre

    def _render_annotation(self, el: "str | dc.Name | dc.Expression | None"):
        if isinstance(el, (type(None), str)):
            return el

        return el.full

    @dispatch
    def to_md(self, el):
        raise NotImplementedError(f"Unsupported type: {type(el)}")

    @dispatch
    def to_md(self, el: str):
        return el

    # TODO: remove, as this is now handled by _render_annotation
    # @dispatch
    # def to_md(self, el: Union[Expression, Name]):
    #    # these are used often for annotations, and full returns it as a string
    #    return el.full

    @dispatch
    def to_md(self, el: dc.Alias):
        return self.to_md(el.target)

    @dispatch
    def to_md(self, el: dc.Object):
        # TODO: replace hard-coded header level

        _str_pars = self.to_md(el.parameters)
        str_sig = f"`{el.name}({_str_pars})`"

        _anchor = f"{{ #{el.name} }}"
        str_title = f"{'#' * self.header_level} {el.name} {_anchor}"

        str_body = []
        if el.docstring is None:
            pass
        else:
            for section in el.docstring.parsed:
                new_el = docstring_section_narrow(section)
                title = new_el.kind.value
                body = self.to_md(new_el)

                if title != "text":
                    header = f"{'#' * (self.header_level + 1)} {title.title()}"
                    str_body.append("\n\n".join([header, body]))
                else:
                    str_body.append(body)

        if self.show_signature:
            parts = [str_title, str_sig, *str_body]
        else:
            parts = [str_title, *str_body]

        return "\n\n".join(parts)

    @dispatch
    def to_md(self, el: dc.Attribute):
        raise NotImplementedError()

    # signature parts -------------------------------------------------------------

    @dispatch
    def to_md(self, el: dc.Parameters):
        return ", ".join(map(self.to_md, el))

    @dispatch
    def to_md(self, el: dc.Parameter):
        # TODO: missing annotation
        splats = {dc.ParameterKind.var_keyword, dc.ParameterKind.var_positional}
        has_default = el.default and el.kind not in splats

        annotation = self._render_annotation(el.annotation)
        if annotation and has_default:
            return f"{el.name}: {el.annotation} = {el.default}"
        elif annotation:
            return f"{el.name}: {el.annotation}"
        elif has_default:
            return f"{el.name}={el.default}"

        return el.name

    # docstring parts -------------------------------------------------------------

    # text ----
    # note this can be a number of things. for example, opening docstring text,
    # or a section with a header not included in the numpydoc standard
    @dispatch
    def to_md(self, el: ds.DocstringSectionText):
        new_el = docstring_section_narrow(el)
        if isinstance(new_el, ds.DocstringSectionText):
            # ensures we don't recurse forever
            return el.value

        return self.to_md(new_el)

    # parameters ----

    @dispatch
    def to_md(self, el: ds.DocstringSectionParameters):
        rows = list(map(self.to_md, el.value))
        header = ["Name", "Type", "Description", "Default"]
        return tabulate(rows, header, tablefmt="github")

    @dispatch
    def to_md(self, el: ds.DocstringParameter) -> Tuple[str]:
        # TODO: if default is not, should return the word "required" (unescaped)
        default = "required" if el.default is None else escape(el.default)

        annotation = self._render_annotation(el.annotation)
        return (escape(el.name), annotation, sanitize(el.description), default)

    # attributes ----

    @dispatch
    def to_md(self, el: ds.DocstringSectionAttributes):
        header = ["Name", "Type", "Description"]
        rows = list(map(self.to_md, el.value))

        return tabulate(rows, header, tablefmt="github")

    @dispatch
    def to_md(self, el: ds.DocstringAttribute):
        annotation = self._render_annotation(el.annotation)
        return el.name, self.to_md(annotation), el.description

    # see also ----

    @dispatch
    def to_md(self, el: DocstringSectionSeeAlso):
        # TODO: attempt to parse See Also sections
        return el.value

    # examples ----

    @dispatch
    def to_md(self, el: ds.DocstringSectionExamples):
        # its value is a tuple: DocstringSectionKind["text" | "examples"], str
        data = map(tuple_to_data, el.value)
        return "\n\n".join(list(map(self.to_md, data)))

    @dispatch
    def to_md(self, el: ExampleCode):
        return f"""```python
{el.value}
```"""

    # returns ----

    @dispatch
    def to_md(self, el: Union[ds.DocstringSectionReturns, ds.DocstringSectionRaises]):
        rows = list(map(self.to_md, el.value))
        header = ["Type", "Description"]
        return tabulate(rows, header, tablefmt="github")

    @dispatch
    def to_md(self, el: Union[ds.DocstringReturn, ds.DocstringRaise]):
        # similar to DocstringParameter, but no name or default
        annotation = self._render_annotation(el.annotation)
        return (annotation, el.description)

    # unsupported parts ----

    @dispatch
    def to_md(self, el: ExampleText):
        return el.value

    @dispatch.multi(
        (ds.DocstringAdmonition,),
        (ds.DocstringDeprecated,),
        (ds.DocstringWarn,),
        (ds.DocstringYield,),
        (ds.DocstringReceive,),
        (ds.DocstringAttribute,),
    )
    def to_md(self, el):
        raise NotImplementedError(f"{type(el)}")