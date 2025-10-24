"""Deterministic microcopy generator for plain-language claim explainers."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

_ALLOWED_PERSONAS = {"patient", "payer", "provider"}
_ALLOWED_LEVELS = {"grade4", "grade6", "grade8", "pro"}
_ALLOWED_LANGUAGES = {"en", "es", "hi"}

_STYLE: dict[str, dict[str, dict[str, str]]] = {
    "patient": {
        "grade4": {
            "charge_present": "We checked claim {doc_id}. The doctor billed {billed} for your care.",
            "charge_missing": "We checked claim {doc_id}, but the doctor’s bill was left blank.",
            "allowed_present": "The health plan says only {allowed} counts under your benefits.",
            "allowed_missing": "The plan did not tell us how much of the bill they consider covered.",
            "patient_present": "They paid {insurer}, took {adjustments} in plan discounts, and still ask you for {patient}. We know that is a lot to shoulder.",
            "patient_known": "Right now they ask you to pay {patient}.",
            "patient_missing": "We cannot tell what they expect from you because key numbers were missing.",
            "flag_line": "Heads-up: {text}",
            "missing_line": "These pieces are still missing: {labels}.",
        },
        "grade6": {
            "charge_present": "For claim {doc_id}, the provider billed {billed}. We’re here to help you make sense of that.",
            "charge_missing": "For claim {doc_id}, the bill amount never came through, which makes review harder.",
            "allowed_present": "The plan only agrees to cover {allowed}; anything above that may feel unfair.",
            "allowed_missing": "The plan never shared the allowed amount, so we’re missing a big clue.",
            "patient_present": "They issued {insurer}, applied {adjustments} as plan discounts, and still land on {patient} for you. We can question that math.",
            "patient_known": "Their worksheet says you owe {patient}.",
            "patient_missing": "We couldn’t confirm your share because the plan left gaps in the data.",
            "flag_line": "Alert: {text}",
            "missing_line": "We still need these details checked: {labels}.",
        },
        "grade8": {
            "charge_present": "Claim {doc_id} shows the provider billed {billed}. Let’s make sure that fits the care you received.",
            "charge_missing": "Claim {doc_id} lacks the billed amount, so the story starts incomplete.",
            "allowed_present": "The plan recognizes only {allowed} under its rules, which can be confusing.",
            "allowed_missing": "The plan withheld the allowed amount, leaving us without a vital number.",
            "patient_present": "They remitted {insurer}, booked {adjustments} as contractual write-offs, and still expect {patient} from you. We’ll flag anything off.",
            "patient_known": "Their calculation still points to {patient} from you.",
            "patient_missing": "Your share stays uncertain because the plan never delivered full data.",
            "flag_line": "Review alert: {text}",
            "missing_line": "We need these missing pieces before we can trust the math: {labels}.",
        },
        "pro": {
            "charge_present": "Claim {doc_id} shows the rendering provider invoiced {billed}. We’ll track every dollar alongside you.",
            "charge_missing": "Claim {doc_id} lacks the invoiced amount, restricting how far we can audit.",
            "allowed_present": "Plan adjudication capped coverage at {allowed}; we can press for that rationale.",
            "allowed_missing": "Plan adjudication never documented the allowed amount, which raises compliance questions.",
            "patient_present": "After the payer remitted {insurer} and booked {adjustments} in contract adjustments, they leave member liability at {patient}. We can contest any mismatch.",
            "patient_known": "Their worksheet still pins member liability at {patient}.",
            "patient_missing": "Member liability cannot be reconciled because adjudication inputs are incomplete.",
            "flag_line": "Compliance alert: {text}",
            "missing_line": "Escalate for these missing datapoints: {labels}.",
        },
    },
    "payer": {
        "grade4": {
            "charge_present": "Claim {doc_id}: provider submitted {billed} per encounter file.",
            "charge_missing": "Claim {doc_id}: submitted charge absent from the record.",
            "allowed_present": "Adjudication allowed {allowed} under the contract.",
            "allowed_missing": "Adjudication lacks the allowed amount, preventing full policy review.",
            "patient_present": "Plan remit of {insurer} and contract adjustments of {adjustments} leave member liability at {patient}.",
            "patient_known": "Member liability remains {patient}.",
            "patient_missing": "Member liability unresolved because source data is incomplete.",
            "flag_line": "Investigate: {text}",
            "missing_line": "Close these gaps before sign-off: {labels}.",
        },
        "grade6": {
            "charge_present": "Claim {doc_id}: provider billed {billed} per submission log.",
            "charge_missing": "Claim {doc_id}: billed amount missing in adjudication archive.",
            "allowed_present": "Plan allowed {allowed} according to reimbursement schedule.",
            "allowed_missing": "Plan records omit the allowed figure; contract terms need confirmation.",
            "patient_present": "With remit {insurer} and contractual adjustments of {adjustments}, member liability stands at {patient}.",
            "patient_known": "Member liability totals {patient} under current audit.",
            "patient_missing": "Member liability cannot be certified because ledger inputs are missing.",
            "flag_line": "Review needed: {text}",
            "missing_line": "Validate these data points: {labels}.",
        },
        "grade8": {
            "charge_present": "Claim {doc_id}: provider submitted {billed} for adjudication.",
            "charge_missing": "Claim {doc_id}: submitted charge not recorded in adjudication system.",
            "allowed_present": "Adjudication allowed {allowed} consistent with contract language.",
            "allowed_missing": "Adjudication notes omitted the allowed threshold, blocking compliance review.",
            "patient_present": "After remit of {insurer} and negotiated adjustments of {adjustments}, member obligation is {patient} pending appeal.",
            "patient_known": "Member obligation stands at {patient} unless appeal succeeds.",
            "patient_missing": "Member obligation remains indeterminate due to missing ledger inputs.",
            "flag_line": "Program integrity alert: {text}",
            "missing_line": "Document these outstanding items: {labels}.",
        },
        "pro": {
            "charge_present": "Claim {doc_id}: provider invoiced {billed} per plan intake.",
            "charge_missing": "Claim {doc_id}: invoiced amount missing from intake package.",
            "allowed_present": "Plan adjudication allowed {allowed} under governing agreement.",
            "allowed_missing": "Plan adjudication lacks the allowed amount, requiring contract reconciliation.",
            "patient_present": "Following remit of {insurer} and contractual adjustments of {adjustments}, member liability is {patient} subject to policy review.",
            "patient_known": "Member liability remains {patient} per worksheet.",
            "patient_missing": "Member liability cannot be reconciled because adjudication inputs remain incomplete.",
            "flag_line": "Program integrity alert: {text}",
            "missing_line": "Escalate for manual reconciliation: {labels}.",
        },
    },
    "provider": {
        "grade4": {
            "charge_present": "Claim {doc_id}: coding team billed {billed} for this visit.",
            "charge_missing": "Claim {doc_id}: billed amount missing—confirm charge entry.",
            "allowed_present": "Payer allowed {allowed}; check contract schedule.",
            "allowed_missing": "Payer did not share the allowed amount for this line.",
            "patient_present": "Plan remitted {insurer}, recorded {adjustments} as adjustments, and left patient balance {patient}. Confirm modifiers support the residual.",
            "patient_known": "Patient balance currently {patient}.",
            "patient_missing": "Patient balance undetermined because ledger inputs are missing.",
            "flag_line": "Check point: {text}",
            "missing_line": "Review missing inputs before closeout: {labels}.",
        },
        "grade6": {
            "charge_present": "Claim {doc_id}: billing submitted {billed} with documented coding and modifiers.",
            "charge_missing": "Claim {doc_id}: billed amount absent—verify coding export.",
            "allowed_present": "Payer allowed {allowed}; align with schedule A allowances.",
            "allowed_missing": "Payer feed omitted the allowed amount, so reconciliation is pending.",
            "patient_present": "Remit posted {insurer} and adjustments of {adjustments}, leaving patient balance {patient}. Confirm modifier rationale.",
            "patient_known": "Patient balance remains {patient} pending QA.",
            "patient_missing": "Patient balance could not be confirmed due to missing ledger data.",
            "flag_line": "Action item: {text}",
            "missing_line": "Resolve these documentation gaps: {labels}.",
        },
        "grade8": {
            "charge_present": "Claim {doc_id}: submitted charges total {billed}; coding and modifiers should mirror documentation.",
            "charge_missing": "Claim {doc_id}: submitted charge absent—validate encounter coding.",
            "allowed_present": "Payer allowed {allowed}; cross-check against contract adjustment tables.",
            "allowed_missing": "Payer records omitted the allowed amount, delaying coding QA.",
            "patient_present": "After payer payment of {insurer} and adjustments of {adjustments}, patient liability stands at {patient}. Ensure modifier usage supports this balance.",
            "patient_known": "Patient liability remains {patient} while audit completes.",
            "patient_missing": "Patient liability unresolved because supporting figures are missing.",
            "flag_line": "Follow-up alert: {text}",
            "missing_line": "Document missing figures for coding QA: {labels}.",
        },
        "pro": {
            "charge_present": "Claim {doc_id}: submitted charge logged as {billed}; confirm coding and modifiers align with operative note.",
            "charge_missing": "Claim {doc_id}: submitted charge not in feed—check coding export.",
            "allowed_present": "Payer adjudication allowed {allowed}; validate against contract matrix and modifier logic.",
            "allowed_missing": "Payer adjudication omitted the allowed amount, blocking reconciliation.",
            "patient_present": "Post-remit of {insurer} and adjustments of {adjustments}, patient liability posts at {patient}. Confirm modifiers justify the remaining balance.",
            "patient_known": "Patient liability currently shows {patient}; confirm modifier rationale.",
            "patient_missing": "Patient liability could not be reconciled because ledger inputs and coding references are incomplete.",
            "flag_line": "Revenue alert: {text}",
            "missing_line": "Collect missing data points for coding QA: {labels}.",
        },
    },
}

_ACRONYM_MAP = {
    "EOB": "Explanation of Benefits (EOB)",
    "CPT": "Current Procedural Terminology (CPT)",
    "OOP": "out-of-pocket",
    "PSL": "patient share lookup",
}

_LANGUAGE_OVERRIDES: dict[str, dict[str, str]] = {
    "es": {
        "charge_present": "Reclamación {doc_id}: el proveedor facturó {billed}.",
        "charge_missing": "Reclamación {doc_id}: el monto facturado no figura.",
        "allowed_present": "El plan permitió {allowed}.",
        "allowed_missing": "El plan no indicó el monto permitido.",
        "patient_present": "Con el pago del plan de {insurer} y ajustes de {adjustments}, debes {patient}.",
        "patient_known": "Tu responsabilidad es {patient}.",
        "patient_missing": "No pudimos confirmar tu responsabilidad porque faltan datos.",
        "flag_line": "Alerta: {text}",
        "missing_line": "Revisa estos datos faltantes: {labels}.",
    },
    "hi": {
        "charge_present": "दावा {doc_id}: प्रदाता ने {billed} का बिल दिया।",
        "charge_missing": "दावा {doc_id}: बिल की गई राशि उपलब्ध नहीं है।",
        "allowed_present": "योजना ने {allowed} की अनुमति दी।",
        "allowed_missing": "योजना ने अनुमत राशि साझा नहीं की।",
        "patient_present": "योजना ने {insurer} का भुगतान किया और समायोजन {adjustments} थे, इसलिए आपका हिस्सा {patient} है।",
        "patient_known": "आपकी जिम्मेदारी {patient} है।",
        "patient_missing": "ज़रूरी डेटा न होने से आपकी जिम्मेदारी स्पष्ट नहीं है।",
        "flag_line": "चेतावनी: {text}",
        "missing_line": "इन अनुपस्थित मदों की जाँच करें: {labels}.",
    },
}

_SEVERITY_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {"high": "Serious concern", "medium": "Needs review", "low": "Note"},
    "es": {"high": "Preocupación grave", "medium": "Revisión necesaria", "low": "Nota"},
    "hi": {"high": "गंभीर चिंता", "medium": "समीक्षा आवश्यक", "low": "नोट"},
}

_FLAG_SUFFIX_TEMPLATES: dict[str, tuple[str, str]] = {
    "en": ("(+{n} more alert)", "(+{n} more alerts)"),
    "es": ("(+{n} alerta adicional)", "(+{n} alertas adicionales)"),
    "hi": ("(+{n} अतिरिक्त चेतावनी)", "(+{n} अतिरिक्त चेतावनियाँ)"),
}

_LABEL_JOINERS: dict[str, dict[str, str]] = {
    "en": {"and": "and", "more": "more"},
    "es": {"and": "y", "more": "más"},
    "hi": {"and": "और", "more": "अधिक"},
}

_MISSING_FALLBACK: dict[str, str] = {
    "en": "key numbers",
    "es": "datos clave",
    "hi": "महत्वपूर्ण आंकड़े",
}


def explain_plain(
    doc_id: str,
    breakdown: Sequence[dict[str, Any]] | None,
    calcs: Sequence[dict[str, Any]] | None,
    risk_flags: Sequence[dict[str, Any]] | None,
    persona: str = "patient",
    level: str = "grade6",
    language: str = "en",
) -> str:
    """Return a bullet list summary tuned for the given persona and reading level."""

    persona_key = persona.lower().strip()
    level_key = level.lower().strip()
    language_key = language.lower().strip()

    if persona_key not in _ALLOWED_PERSONAS:
        raise ValueError(f"Unsupported persona '{persona}'.")
    if level_key not in _ALLOWED_LEVELS:
        raise ValueError(f"Unsupported level '{level}'.")
    if language_key not in _ALLOWED_LANGUAGES:
        raise ValueError(f"Unsupported language '{language}'.")

    style = _STYLE[persona_key][level_key]

    values = _extract_values(breakdown or [])
    billed = values.get("Amount Billed")
    allowed = values.get("Allowed Amount")
    insurer_paid = values.get("Insurer Paid")
    adjustments = values.get("Adjustments")
    patient_resp = values.get("Patient Responsibility")

    missing_labels = _collect_missing_labels(values, calcs or [])
    labels_text = _format_label_list(missing_labels, language_key)

    lines: list[str] = []

    if billed is not None:
        charge_template = _resolve_template(style, "charge_present", language_key)
        charge_line = charge_template.format(doc_id=doc_id, billed=_fmt_money(billed))
    else:
        charge_template = _resolve_template(style, "charge_missing", language_key)
        charge_line = charge_template.format(doc_id=doc_id)
    lines.append(charge_line)

    if allowed is not None:
        allowed_template = _resolve_template(style, "allowed_present", language_key)
        allowed_line = allowed_template.format(allowed=_fmt_money(allowed))
    else:
        allowed_template = _resolve_template(style, "allowed_missing", language_key)
        allowed_line = allowed_template.format(allowed="")
    lines.append(allowed_line)

    if patient_resp is not None and insurer_paid is not None and adjustments is not None:
        patient_template = _resolve_template(style, "patient_present", language_key)
        patient_line = patient_template.format(
            insurer=_fmt_money(insurer_paid),
            adjustments=_fmt_money(adjustments),
            patient=_fmt_money(patient_resp),
        )
    elif patient_resp is not None:
        patient_template = _resolve_template(style, "patient_known", language_key)
        patient_line = patient_template.format(patient=_fmt_money(patient_resp))
    else:
        patient_template = _resolve_template(style, "patient_missing", language_key)
        patient_line = patient_template.format()
    lines.append(patient_line)

    flag_line = _render_flag_line(style, risk_flags or [], language_key)
    if flag_line:
        lines.append(flag_line)

    if missing_labels:
        missing_template = _resolve_template(style, "missing_line", language_key)
        fallback_label = _MISSING_FALLBACK.get(language_key, _MISSING_FALLBACK["en"])
        missing_line = missing_template.format(labels=labels_text or fallback_label)
        lines.append(missing_line)

    trimmed = [_expand_acronyms(line.strip()) for line in lines if line.strip()]

    # Ensure output respects the 2-5 bullet requirement by trimming overflow if needed.
    if len(trimmed) > 5:
        trimmed = trimmed[:5]

    if len(trimmed) < 2:
        return "\n".join(f"- {line}" for line in trimmed)

    return "\n".join(f"- {line}" for line in trimmed)


def _extract_values(entries: Sequence[dict[str, Any]]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for entry in entries:
        label = str(entry.get("label", "")).strip()
        if not label:
            continue
        raw_value = entry.get("value")
        values[label] = _safe_float(raw_value)
    return values


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _collect_missing_labels(values: dict[str, float | None], calcs: Sequence[dict[str, Any]]) -> list[str]:
    missing: set[str] = {label for label, amount in values.items() if amount is None}
    for calc in calcs:
        if calc.get("unverifiable"):
            label = str(calc.get("label", "")).strip()
            if label:
                missing.add(label)
    return sorted(missing)


def _format_label_list(labels: Iterable[str], language: str) -> str:
    items = [label for label in labels if label]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    joiner = _LABEL_JOINERS.get(language, _LABEL_JOINERS["en"])
    and_word = joiner["and"]
    more_word = joiner["more"]
    if len(items) == 2:
        return f"{items[0]} {and_word} {items[1]}"
    remainder = len(items) - 2
    return f"{items[0]}, {items[1]} {and_word} {remainder} {more_word}"


def _render_flag_line(
    style: dict[str, str], flags: Sequence[dict[str, Any]], language: str
) -> str | None:
    if not flags:
        return None
    primary = flags[0]
    extra_count = max(0, len(flags) - 1)
    severity_text = _severity_phrase(str(primary.get("severity", "")).lower(), language)
    rationale = primary.get("rationale") or primary.get("label") or "Additional review suggested."
    flag_text = f"{severity_text}: {rationale}"
    if extra_count:
        flag_text = f"{flag_text} {_extra_alert_suffix(language, extra_count)}"
    clean_text = _expand_acronyms(flag_text)
    template = _resolve_template(style, "flag_line", language)
    return template.format(text=clean_text)


def _severity_phrase(severity: str, language: str) -> str:
    phrases = _SEVERITY_TRANSLATIONS.get(language, _SEVERITY_TRANSLATIONS["en"])
    return phrases.get(severity, phrases.get("low", "Note"))


def _extra_alert_suffix(language: str, count: int) -> str:
    singular, plural = _FLAG_SUFFIX_TEMPLATES.get(language, _FLAG_SUFFIX_TEMPLATES["en"])
    template = singular if count == 1 else plural
    return template.format(n=count)


def _expand_acronyms(text: str) -> str:
    updated = text
    for token, replacement in _ACRONYM_MAP.items():
        if token in updated and replacement not in updated:
            updated = updated.replace(token, replacement)
    return updated


def _resolve_template(style: dict[str, str], key: str, language: str) -> str:
    if language != "en":
        template = _LANGUAGE_OVERRIDES.get(language, {}).get(key)
        if template:
            return template
    return style[key]