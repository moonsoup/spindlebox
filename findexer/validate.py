"""The 'compile-time validation' pass: every item has the expected interface.

Checks (errors → non-zero exit from the CLI):
- every op_array is signature-homogeneous (one element type per array)
- signature_classes membership matches each item's actual signature
- ctx_schema is type-consistent with every adapter's requires/provides
- pipelines are type-sound stage to stage (direct chain or ctx chain)
- ordinal integrity (unique, not retired, group members exist)

Warnings (errors under --strict): 'any'-bearing signatures.
"""

from __future__ import annotations

from findexer.schema import ScaIndex
from findexer.sigclass import sig_class_id


def validate_index(index: ScaIndex, strict: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    by_ordinal = {}

    for item in index.items:
        if item.ordinal in by_ordinal:
            errors.append(
                f"duplicate ordinal {item.ordinal}: '{by_ordinal[item.ordinal].address}' "
                f"and '{item.address}'"
            )
        by_ordinal[item.ordinal] = item
        if item.ordinal in index.retired_ordinals:
            errors.append(f"ordinal {item.ordinal} ('{item.address}') is in retired_ordinals")
        actual = sig_class_id(item.signature)
        if actual != item.sig_class:
            errors.append(
                f"item '{item.address}': declared sig_class '{item.sig_class}' does not "
                f"match its actual signature '{actual}'"
            )
        anys = [p.name for p in item.signature.params if "any" in p.norm_type]
        if "any" in item.signature.returns_norm:
            anys.append("<return>")
        if anys:
            msg = f"item '{item.address}': untyped ('any') in {', '.join(anys)}"
            (errors if strict else warnings).append(msg)

    for sc_id, sc in index.signature_classes.items():
        for ordinal in sc.get("members", []):
            item = by_ordinal.get(ordinal)
            if item is None:
                errors.append(f"signature_class '{sc_id}' references unknown ordinal {ordinal}")
            elif item.sig_class != sc_id:
                errors.append(
                    f"signature_class '{sc_id}' member {ordinal} ('{item.address}') "
                    f"actually has sig_class '{item.sig_class}'"
                )

    for root in index.groups:
        for group in root.walk():
            for ordinal in group.member_ordinals:
                if ordinal not in by_ordinal:
                    errors.append(f"group '{group.path}' references unknown ordinal {ordinal}")
            for sig, ordinals in group.op_arrays.items():
                for ordinal in ordinals:
                    item = by_ordinal.get(ordinal)
                    if item is None:
                        errors.append(
                            f"op_array '{sig}' in group '{group.path}' references "
                            f"unknown ordinal {ordinal}"
                        )
                    elif item.sig_class != sig:
                        errors.append(
                            f"op_array '{sig}' in group '{group.path}' is not homogeneous: "
                            f"member {ordinal} ('{item.address}') has sig_class "
                            f"'{item.sig_class}'"
                        )

    for item in index.items:
        for key, t in {**item.ctx_adapter.requires, **item.ctx_adapter.provides}.items():
            declared = index.ctx_schema.get(key)
            if declared is None:
                errors.append(f"ctx key '{key}' (item '{item.address}') missing from ctx_schema")
            elif declared != t:
                errors.append(
                    f"ctx key '{key}' type conflict: schema says '{declared}', "
                    f"item '{item.address}' uses '{t}'"
                )

    for pipe in index.pipelines:
        stages = [by_ordinal.get(o) for o in pipe.stages]
        missing = [o for o, s in zip(pipe.stages, stages, strict=True) if s is None]
        if missing:
            errors.append(f"pipeline '{pipe.name}' references unknown ordinals {missing}")
            continue
        available = set(stages[0].ctx_adapter.requires)
        available |= set(stages[0].ctx_adapter.provides)
        for prev, cur in zip(stages, stages[1:], strict=False):
            required_params = [
                p for p in cur.signature.params
                if p.kind not in ("receiver", "kwvariadic") and p.default is None
            ]
            direct = (
                len(required_params) == 1
                and required_params[0].norm_type == prev.signature.returns_norm
            )
            ctx_ok = set(cur.ctx_adapter.requires) <= available
            if not (direct or ctx_ok):
                lacking = sorted(set(cur.ctx_adapter.requires) - available)
                errors.append(
                    f"pipeline '{pipe.name}': stage '{cur.address}' cannot follow "
                    f"'{prev.address}' — no direct chain (needs "
                    f"{[p.norm_type for p in required_params]}, gets "
                    f"'{prev.signature.returns_norm}') and ctx keys {lacking} are unprovided"
                )
            available |= set(cur.ctx_adapter.provides)
    return errors, warnings
