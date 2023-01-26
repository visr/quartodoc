# from importlib.resources import files
from quartodoc import MdRenderer
from plum import dispatch
from typing import Union
from pathlib import Path

from griffe import dataclasses as dc


# Note that quarto can't find files outside the project root, so we'll need
# to git clone the plotnine-examples repo
# EXAMPLES_PATH = files('plotnine_examples')
EXAMPLES_PATH = Path("plotnine-examples/plotnine_examples")


class Renderer(MdRenderer):
    style = "plotnine"

    @dispatch
    def to_md(self, el: Union[dc.Object, dc.Alias]):
        rendered = super().to_md(el)

        p_example = EXAMPLES_PATH / "examples" / (el.name + ".ipynb")
        if p_example.exists():
            path = "/" + str(p_example)
            return rendered + f"\n\nExamples\n------\n\n{{{{< embed {path} >}}}}"

        return rendered
