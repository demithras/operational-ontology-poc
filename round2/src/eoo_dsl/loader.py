"""Strict YAML loader: no anchors/aliases/tags/merge keys, no duplicate keys, one document, YAML-1.2-core scalars.

PyYAML's default resolver is YAML 1.1 (yes/no/on/off booleans, sexagesimal ints, octal, timestamps, '<<' merge).
Those make a hand-written value mean something other than what it looks like, so they are removed here: the only
implicit scalars are null, true/false, decimal integers and decimal floats; everything else is a string.
"""
from __future__ import annotations

import re

from yaml import events
from yaml.composer import Composer
from yaml.constructor import ConstructorError, SafeConstructor
from yaml.error import YAMLError
from yaml.parser import Parser
from yaml.reader import Reader
from yaml.resolver import BaseResolver
from yaml.scanner import Scanner

from .errors import DslAliasError, DslDuplicateKey, DslSurfaceAmbiguity, DslSyntaxError


class _Resolver(BaseResolver):
    pass


_Resolver.add_implicit_resolver("tag:yaml.org,2002:null", re.compile(r"^(?:null|)$"), ["n", ""])
_Resolver.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))
_Resolver.add_implicit_resolver("tag:yaml.org,2002:int", re.compile(r"^-?(?:0|[1-9][0-9]*)$"), list("-0123456789"))
_Resolver.add_implicit_resolver(
    "tag:yaml.org,2002:float", re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"), list("-0123456789"))


class _Loader(Reader, Scanner, Parser, Composer, SafeConstructor, _Resolver):
    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        SafeConstructor.__init__(self)
        _Resolver.__init__(self)

    def compose_node(self, parent, index):
        if self.check_event(events.AliasEvent):
            raise DslAliasError("YAML aliases are not allowed in the DSL")
        ev = self.peek_event()
        if getattr(ev, "anchor", None) is not None:
            raise DslAliasError("YAML anchors are not allowed in the DSL")
        tag = getattr(ev, "tag", None)
        if tag is not None:
            raise DslAliasError(f"explicit YAML tag {tag!r} is not allowed in the DSL")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str):
                raise DslSurfaceAmbiguity(f"mapping key {key!r} is not a string", f"line {key_node.start_mark.line + 1}")
            if key in seen:
                raise DslDuplicateKey(f"duplicate key {key!r}", f"line {key_node.start_mark.line + 1}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load(text: str):
    """Parse exactly one YAML document with the strict rules above. Raises DslError subclasses only."""
    if not isinstance(text, str):
        raise DslSyntaxError("DSL input must be text")
    try:
        loader = _Loader(text)
        try:
            if not loader.check_node():
                raise DslSyntaxError("empty document")
            node = loader.get_node()
            if loader.check_node():
                raise DslSurfaceAmbiguity("more than one YAML document in the input")
            return loader.construct_document(node)
        finally:
            loader.dispose()
    except DslSyntaxError:
        raise
    except (DslAliasError, DslSurfaceAmbiguity):
        raise
    except (YAMLError, ConstructorError) as exc:
        raise DslSyntaxError(str(exc).replace("\n", " ")) from exc
    except (ValueError, OverflowError, RecursionError) as exc:
        raise DslSyntaxError(f"{type(exc).__name__}: {exc}") from exc

