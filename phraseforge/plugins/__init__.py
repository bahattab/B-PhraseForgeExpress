"""Plugins (PRD G-13, FR-PLG-01/02/04/07/08), stage 1.

A plugin is a folder or a .pfplugin zip with a plugin.toml (manifest.py). It is installed
into <data>/plugins/<id> after the user has seen and accepted its permissions (install.py),
and runs as its own process that speaks JSON-RPC 2.0 over stdin/stdout (host.py), with a
time limit per call; a plugin that hangs is killed. Macro plugins add {#<id>.<name>}
commands, namespaced so they cannot replace built-in macros (manager.py).

Plugins, their switches and their secrets belong to this PC: sync never brings a plugin.
"""
