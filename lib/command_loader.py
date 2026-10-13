"""
Command loader with optional lazy import and metadata extraction.

Metadata is extracted without importing the module:
    - DESCRIPTION, USAGE, PARAMS, EXAMPLES, HIDDEN from module globals
    - PARAMS auto-derived from `args.get('...')` calls if not set
    - EXAMPLES auto-generated from PARAMS if not set

Public API
----------
    load_commands() -> dict[str, dict]      -- scan + cache metadata
    metadata() -> dict[str, dict]           -- cached metadata (no import)
    get_command(name) -> dict | None        -- import on demand
    add_plugin_commands(plugin, path)       -- register plugin command dir
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("homer.command_loader")


class CommandLoader:
    def __init__(self, commands_dir: Path, *, root_dir: Optional[Path] = None):
        self.commands_dir = Path(commands_dir)
        self.root_dir = Path(root_dir) if root_dir else self.commands_dir.parent
        self.plugin_dirs: list[tuple[str, Path]] = []
        self._loaded: dict[str, dict[str, Any]] = {}

    # ─────────── Plugin registration ───────────

    def add_plugin_commands(self, plugin_name: str, plugin_commands_dir: Path) -> None:
        self.plugin_dirs.append((plugin_name, Path(plugin_commands_dir)))

    # ─────────── Loading ───────────

    def load_commands(self) -> dict[str, dict[str, Any]]:
        """
        Scan user and plugin command directories.
        Returns (and caches) a dict of metadata. Modules are NOT imported.
        """
        commands: dict[str, dict[str, Any]] = {}

        # User commands
        if self.commands_dir.exists():
            for py in self.commands_dir.rglob("*.py"):
                if py.name == "__init__.py":
                    continue
                name = self._get_command_name(py, self.commands_dir)
                if not name:
                    continue
                meta = self._metadata_only(py, name, source="user")
                if meta:
                    commands[name] = meta

        # Plugin commands
        for plugin_name, pdir in self.plugin_dirs:
            if not pdir.exists():
                continue
            for py in pdir.rglob("*.py"):
                if py.name == "__init__.py":
                    continue
                local = self._get_command_name(py, pdir)
                if not local:
                    continue
                full = f"{plugin_name}:{local}"
                meta = self._metadata_only(py, full, source=f"plugin:{plugin_name}")
                if meta:
                    commands[full] = meta

        self._loaded = commands
        return commands

    def metadata(self) -> dict[str, dict[str, Any]]:
        """
        Return cached metadata for all commands. Triggers a scan on
        first call. No modules are imported.
        """
        if not self._loaded:
            self.load_commands()
        return self._loaded

    def get_command(self, name: str) -> Optional[dict[str, Any]]:
        """
        Return metadata for a single command with `execute` callable.
        Imports the module on demand (lazy mode).
        """
        if not self._loaded:
            self.load_commands()
        info = self._loaded.get(name)
        if not info:
            return None

        if info.get("lazy"):
            try:
                module = self._import_module(info["path"])
            except Exception as e:
                _log.error("Failed to import command '%s' from %s: %s",
                           name, info["path"], e, exc_info=True)
                return None
            info.update({
                "module": module,
                "execute": getattr(module, "execute", None),
                "lazy": False,
            })
            if info["execute"] is None:
                _log.warning("Command '%s' has no execute() function", name)
                return None
        return info

    # ─────────── Metadata extraction (no import) ───────────

    def _metadata_only(self, py_file: Path, name: str, *, source: str
                       ) -> Optional[dict[str, Any]]:
        try:
            source_text = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            source_text = ""

        meta = self._extract_metadata_ast(source_text, name)
        return {
            "path": py_file,
            "description": meta.get("description", ""),
            "usage": meta.get("usage", ""),
            "params": meta.get("params", {}),
            "examples": meta.get("examples", []),
            "hidden": meta.get("hidden", False),
            "source": source,
            "lazy": True,
            "module": None,
            "execute": None,
        }

    @staticmethod
    def _extract_metadata_ast(source: str, name: str) -> dict[str, Any]:
        """
        Extract module-level metadata and auto-derive PARAMS from
        `args.get('key'[, default])` calls.

        Never raises: on any parse failure returns what was found so far.
        """
        result: dict[str, Any] = {}

        # ── Simple regex pass: DESCRIPTION / USAGE / HIDDEN ──
        m = re.search(r"^\s*DESCRIPTION\s*=\s*(['\"])(.+?)\1",
                      source, re.MULTILINE | re.DOTALL)
        if m:
            result["description"] = m.group(2).strip()
        else:
            # Fallback: first line of docstring
            m = re.search(r'^\s*(?:"""|\'\'\')\s*(.+?)(?:\n|(?:"""|\'\'\'))',
                          source, re.MULTILINE)
            if m:
                result["description"] = m.group(1).strip()

        m = re.search(r"^\s*USAGE\s*=\s*(['\"])(.+?)\1",
                      source, re.MULTILINE | re.DOTALL)
        if m:
            result["usage"] = m.group(2).strip()

        if re.search(r"^\s*HIDDEN\s*=\s*True", source, re.MULTILINE):
            result["hidden"] = True

        # ── AST pass: PARAMS / EXAMPLES / args.get('...') ──
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return result

        parsed_params: dict[str, str] = {}
        parsed_examples: list[str] = []
        seen_arg_keys: set[str] = set()
        arg_defaults: dict[str, Any] = {}

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "PARAMS" and isinstance(node.value, ast.Dict):
                    parsed_params = CommandLoader._ast_dict_of_str(node.value)
                elif target.id == "EXAMPLES" and isinstance(
                        node.value, (ast.List, ast.Tuple)):
                    parsed_examples = [
                        elt.value for elt in node.value.elts
                        if isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)
                    ]

        # Walk the AST for `<something>.get('key'[, default])`
        class _ArgVisitor(ast.NodeVisitor):
            def visit_Call(self, node_call: ast.Call):
                func = node_call.func
                if isinstance(func, ast.Attribute) and func.attr == "get":
                    if node_call.args and isinstance(node_call.args[0], ast.Constant):
                        key = node_call.args[0].value
                        if isinstance(key, str):
                            seen_arg_keys.add(key)
                            default = None
                            if len(node_call.args) >= 2:
                                try:
                                    default = ast.literal_eval(node_call.args[1])
                                except Exception:
                                    default = None
                            elif node_call.keywords:
                                for kw in node_call.keywords:
                                    if kw.arg == "default":
                                        try:
                                            default = ast.literal_eval(kw.value)
                                        except Exception:
                                            default = None
                            arg_defaults[key] = default
                self.generic_visit(node_call)

        _ArgVisitor().visit(tree)

        # Merge: explicit PARAMS override auto-derived
        if not parsed_params and seen_arg_keys:
            auto: dict[str, str] = {}
            for key in sorted(seen_arg_keys):
                default = arg_defaults.get(key)
                if default is not None:
                    auto[key] = f"Optional (default: {default!r})"
                else:
                    auto[key] = "Optional"
            parsed_params = auto

        if parsed_params:
            result["params"] = parsed_params

        # Minimal example if not set and we have params
        if not parsed_examples and parsed_params:
            keys = list(parsed_params.keys())[:2]
            example = name
            for k in keys:
                example += f" --{k}=<value>"
            parsed_examples = [example]

        if parsed_examples:
            result["examples"] = parsed_examples

        return result

    @staticmethod
    def _ast_dict_of_str(node: ast.Dict) -> dict[str, str]:
        out: dict[str, str] = {}
        for k_node, v_node in zip(node.keys, node.values):
            if isinstance(k_node, ast.Constant) and isinstance(k_node.value, str):
                if isinstance(v_node, ast.Constant) and isinstance(v_node.value, str):
                    out[k_node.value] = v_node.value
                else:
                    try:
                        out[k_node.value] = str(ast.literal_eval(v_node))
                    except Exception:
                        out[k_node.value] = ""
        return out

    # ─────────── Import ───────────

    def _import_module(self, path: Path):
        rel = path.relative_to(self.root_dir) if path.is_absolute() else path
        mod_name = (
            "homer_cmd_"
            + str(rel).replace("/", "_").replace("\\", "_").replace(".py", "")
        )
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if not spec or not spec.loader:
            raise ImportError(f"cannot load spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _get_command_name(py_file: Path, base: Path) -> Optional[str]:
        rel = py_file.relative_to(base)
        parts = list(rel.parts)
        parts[-1] = parts[-1].replace(".py", "")
        if parts[-1] == "main":
            parts = parts[:-1]
            if not parts:
                return None
        return ":".join(parts)
