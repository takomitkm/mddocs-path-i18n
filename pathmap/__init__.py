"""pathmap -- path-level localisation for Markdown trees.

Rename directories and files into another language, and rewrite every
internal reference so the result is still a working vault/site.

    from pathmap import MapFile, Rules, Options, run_apply, run_verify

    mapfile = MapFile.load("pathmap.map.tsv")
    rules = Rules.load("keep.txt", "skip.txt")
    run_apply("vault", "build/zh", mapfile, rules)
    result = run_verify("vault", "build/zh", mapfile, rules)
    assert result.ok, result.dead_links
"""

from .apply import PathmapError, Summary, run_apply
from .links import Options, Report, iter_refs, mask_code, rewrite_text
from .plan import Item, Plan, build_plan, translate_path
from .rules import Entry, MapFile, Rules
from .scan import run_scan
from .util import SENTINEL
from .verify import VerifyResult, run_verify

__version__ = "0.1.0"

__all__ = [
    "Entry",
    "Item",
    "MapFile",
    "Options",
    "PathmapError",
    "Plan",
    "Report",
    "Rules",
    "SENTINEL",
    "Summary",
    "VerifyResult",
    "__version__",
    "build_plan",
    "iter_refs",
    "mask_code",
    "rewrite_text",
    "run_apply",
    "run_scan",
    "run_verify",
    "translate_path",
]