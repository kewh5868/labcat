"""Server-owned scope decisions; prompts and history remain search hints
only."""

import html
import re
import unicodedata

QUESTIONS = (
    "Which material, material class, or materials property would you like to study?",
    "What application or research question should the comparison address?",
    "Which properties or constraints matter most for the comparison?",
)
REASONS = {
    "accepted",
    "research_boundary",
    "harmful_manufacture",
    "materials_scope_needed",
    "research_details_needed",
    "model_scope_uncertain",
    "model_declined",
    "assessment_missing",
}


def normalized(value):
    # Match the source-text screen's bounded entity normalization. This value
    # is used only for intake checks; original requests remain unchanged.
    for _ in range(2):
        value = html.unescape(value)
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", value)
        if unicodedata.category(c) != "Cf"
    ).casefold()


def harmful_manufacture(prompt):
    """Match enabling intent and harmful targets together, not isolated
    terms."""
    text = " ".join(normalized(prompt).split())
    clauses = re.split(r"[.!?;]|\bbut\b|\bhowever\b", text)
    target = (
        r"(?:bombs?|warheads?|weapons?|firearms?|gun[ -]?barrels?|bullets?|"
        r"chemical weapons?|bioweapons?|nuclear weapons?|"
        r"nerve agents?|ammunition|munitions|improvised explosive devices?|"
        r"homemade explosives?|explosives?|propellants?|incendiary devices?|"
        r"weapon[ -]?grade materials?)"
    )
    action = (
        r"(?:make|manufactur\w*|build|design|assembl\w*|produc\w*|synthesi\w*|"
        r"formulat\w*|optim\w*|improv\w*|construct|weaponiz\w*|recipe|instructions|"
        r"protocol|steps|increase|maximize|select|rank|recommend|find|choose)"
    )
    for clause in clauses:
        # Intent to harm people is unsafe even without a weapon name. Keep the
        # object explicit so catalyst poisoning and toxicity prevention remain
        # ordinary materials research. Hypothetical/authority framing grants no
        # exception to this boundary.
        for harmful_use in re.finditer(
            r"\b(?:poison\w*|harm\w*|kill\w*|injur\w*|incapacitat\w*|"
            r"wound(?:s|ed|ing)?|hurt(?:s|ing)?)\b"
            r"\s+(?:(?:a|an|the|my|your|other|another|any|unsuspecting|innocent)"
            r"\s+){0,3}(?:persons?|people|humans?|crowds?|civilians?|victims?|"
            r"someone|others|neighbou?rs?|coworkers?|colleagues?|partners?|"
            r"occupants?|residents?|bystanders?)\b",
            clause,
        ):
            prefix = clause[: harmful_use.start()]
            # Plural injury nouns can precede a human subject in a relative
            # clause ("treat wounds people suffer"). Require both that local
            # grammatical role and a protective action; merely mentioning
            # healthcare elsewhere must not excuse a later harmful request.
            injury_noun = harmful_use.group().split()[0] in {"wounds", "injuries"}
            protective_noun = (
                injury_noun
                and re.search(
                    r"\b(?:(?:dressings?|treatments?|care)\s+for|"
                    r"reduce|minimize|prevent|treat|heal)\s*$",
                    prefix,
                )
                and re.match(
                    r"\s+(?:experience|suffer|sustain)(?:s|ed)?\b",
                    clause[harmful_use.end() :],
                )
            )
            if protective_noun:
                continue
            if not negated_action(prefix) and not re.search(
                r"\b(?:prevent\w*|avoid\w*|not|protect\w* against|risk of)"
                r"\s*$|\b(?:instead of|alternatives to)\s+"
                r"(?:\w+\s+){0,5}(?:that|which)\s*$|"
                r"\b(?:prevent\w*|stop\w*|keep\w*)\s+"
                r"(?:(?!and\b|or\b|but\b|however\b)\w+[ -]+){1,8}from\s*$",
                prefix,
            ):
                return True

        targets = [
            match
            for match in re.finditer(r"\b" + target + r"\b", clause)
            if not _protective_target(clause, match)
        ]
        # Inspect every action independently: negating an earlier action does
        # not negate a later harmful instruction in the same clause.
        actions = list(re.finditer(r"\b" + action + r"\b", clause))
        positive_actions = [
            match for match in actions if not negated_action(clause[: match.start()])
        ]
        for match in positive_actions:
            following = clause[match.end() : match.end() + 160]
            if any(
                match.end() <= harmful.start() <= match.end() + 160
                for harmful in targets
            ):
                return True
            # A stated weapons application can precede the enabling action.
            # Bind it to that application, rather than letting an unrelated
            # earlier mention override a later benign materials question.
            if any(
                0 <= match.start() - harmful.end() <= 160
                and re.search(
                    r"\b(?:for|inside|used in|intended for)\s+"
                    r"(?:(?:a|an|the|new)\s+){0,2}$",
                    clause[: harmful.start()],
                )
                for harmful in targets
            ):
                return True
            if re.search(r"\b(?:lethality|blast yield|armor penetration)\b", following):
                return True
        if (not actions or positive_actions) and any(
            re.search(
                r"\b(?:materials?|alloys?|compositions?|properties)\b"
                r".{0,45}\bfor\b.{0,55}$",
                clause[: harmful.start()],
            )
            for harmful in targets
        ):
            return True
    return False


def _protective_target(clause, target):
    """A safety exception belongs to one target, never the entire
    clause."""
    before, after = clause[: target.start()], clause[target.end() :]
    return bool(
        (
            target.group() == "explosive"
            and re.match(r"\s+(?:crystal growth|crystallization)\b", after)
        )
        or re.match(
            r"\s+(?:detectors?|detection|" r"disposal|remediation|decontamination)\b",
            after,
        )
        or re.search(
            r"\b(?:(?:detect\w*|remediat\w*|disposal|decontaminat\w*)\s+"
            r"(?:(?:of|against|from|for)\s+)?|protect\w*\s+(?:against|from)\s+)"
            r"(?:(?:a|an|the|chemical|biological)\s+){0,2}$",
            before,
        )
    )


def negated_action(prefix):
    if re.search(r"\bwithout\s+(?:ever\s+)?$", prefix):
        # "Work without reading private records" prohibits that action;
        # "cannot work without reading them" instead makes it a requirement.
        # Keep this distinction local and do not treat ordinary must/need-to
        # work WITHOUT private access as permission to access private data.
        clause = re.split(r"[.!?;\n]|\b(?:but|however|instead|then)\b", prefix[-240:])[
            -1
        ]
        return not re.search(
            r"\b(?:cannot|can't|could not|couldn't|do not|don't|will not|won't|"
            r"would not|wouldn't|not possible|impossible|unable)\b"
            r".{0,160}\bwithout\s+(?:ever\s+)?$",
            clause,
        )
    if re.search(
        r"\b(?:do not|don't|never|must not|avoid|prevent|cannot|can't)"
        r"\s+(?:ever\s+)?$",
        prefix,
    ):
        return True
    # A coordinated prohibition retains its negation: "do not read X or reveal
    # Y". Commas, sentence/contrast boundaries and an explicit new action break
    # that scope; "do not read X, reveal Y instead" is still refused. Do not
    # propagate "prevent corrosion" into "and improve weapons".
    clause = re.split(r"[.!?;,\n]|\b(?:but|however|instead|then)\b", prefix[-200:])[-1]
    return bool(
        re.search(
            r"\b(?:do not|don't|never|must not|cannot|can't)\s+"
            r"[\w -]{1,140}\s+(?:and|or)\s*$",
            clause,
        )
    )


def decision(status, reason_code):
    return {
        "status": status,
        "reason_code": reason_code,
        "questions": list(QUESTIONS) if status == "clarification_required" else [],
    }


def validate_intake(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"status", "reason_code", "questions"}
        or value["status"] not in {"accepted", "clarification_required", "refused"}
        or value["reason_code"] not in REASONS
        or value["questions"]
        != (list(QUESTIONS) if value["status"] == "clarification_required" else [])
    ):
        raise ValueError("Invalid server intake outcome.")
    return {**value, "questions": list(value["questions"])}


def assess(prompt, *, context=None):
    """Return a closed decision and bounded same-chat user search
    context."""
    from labcat.science import request_violation

    violation = request_violation(prompt)
    if violation:
        return (
            decision(
                "refused",
                (
                    "harmful_manufacture"
                    if isinstance(prompt, str) and harmful_manufacture(prompt)
                    else "research_boundary"
                ),
            ),
            prompt,
        )
    messages = context.get("intake_messages", []) if isinstance(context, dict) else []
    entries = (
        [
            m
            for m in messages[-4:]
            if isinstance(m, dict)
            and m.get("role") == "user"
            and isinstance(m.get("content"), str)
        ]
        if isinstance(messages, list)
        else []
    )
    current = _scope(prompt)
    reset = resets_scope(prompt)
    # Once a benign new scope is established, its later replies must not be
    # poisoned by an older refused task still inside the bounded history window.
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if entry.get("refused") is not True and resets_scope(entry["content"]):
            entries = entries[index:]
            break
    previous = []
    if not reset:
        for entry in entries:
            earlier = entry["content"][:500]
            if entry.get("refused") is True or request_violation(earlier):
                reason = entry.get("reason_code")
                if reason not in {
                    "harmful_manufacture",
                    "research_boundary",
                    "model_declined",
                }:
                    reason = (
                        "harmful_manufacture"
                        if harmful_manufacture(earlier)
                        else "research_boundary"
                    )
                return decision("refused", reason), prompt
            previous.append(earlier)
    # A property-only refinement still needs this chat's composition preferences.
    # Explicit new composition/class hints remain authoritative search preferences.
    from labcat.science.preferences import derive_search_filters

    active = context.get("active_chat", {}) if isinstance(context, dict) else {}
    generic_refinement = (
        isinstance(active, dict)
        and bool(active.get("latest_completed_report_id"))
        and not any(
            key in derive_search_filters(prompt)
            for key in ("formula", "chemsys", "elements", "is_metal")
        )
    )
    # A concrete standalone question need not inherit an unrelated old topic.
    query = prompt
    if (current["status"] != "accepted" or generic_refinement) and previous:
        # Trim only optional history; the whole current request must reach the
        # model's intent assessment, including a potentially unsafe final clause.
        remaining = max(0, 20_000 - len(prompt) - 1)
        history = "\n".join(previous)[-remaining:] if remaining else ""
        if history:
            query = history + "\n" + prompt
    return _scope(query), query


def resets_scope(prompt):
    """A concrete, benign standalone request can explicitly establish
    new scope."""
    from labcat.science import request_violation

    if request_violation(prompt):
        return False
    text = normalized(prompt)
    explicit_reset = re.search(
        r"\b(?:new topic|new question|unrelated question)\b", text
    )
    benign_application = re.search(
        r"\b(?:food packaging|water filtration|medical implants|solar cells|"
        r"building insulation|consumer electronics|biodegradable packaging)\b",
        text,
    )
    continuation = re.search(r"\b(?:it|its|that device|the device|same device)\b", text)
    return bool(
        _scope(prompt)["status"] == "accepted"
        and (explicit_reset or benign_application)
        and not continuation
    )


def _scope(query):
    text = normalized(query)
    # Concrete subjects/properties suffice; saved ranking preferences can supply
    # priorities. Generic 'materials' alone does not select an unrelated class.
    terms = (
        r"\b(?:oxides?|dielectrics?|polymers?|perovsk\w*|ceramics?|"
        r"metals?|alloys?|mofs?|"
        r"semiconduct\w*|nanocrystals?|quantum dots?|composites?|biomaterials?|"
        r"elastomers?|liquid crystals?|thermosets?|thermoplastics?|batter\w*|"
        r"electrodes?|electrolytes?|"
        r"catalysts?|photovoltaic\w*|superconduct\w*|graphene|silicon|titania|alumina|"
        r"steel|glass|membranes?|corrosion|metallurg\w*|crystall\w*|band[ -]?gaps?|"
        r"conductivity|permittivity|refractive index|ballistic transport|tensile|"
        r"magnet\w*|piezoelectr\w*|ferroelectr\w*|porosity|density|thermal expansion)\b"
    )
    if re.search(terms, text) or re.search(r"\b(?:[A-Z][a-z]?\d*){2,}\b", query):
        return decision("accepted", "accepted")
    return decision(
        "clarification_required",
        (
            "research_details_needed"
            if re.search(r"\b(?:materials?|research|properties|candidates?)\b", text)
            else "materials_scope_needed"
        ),
    )


def outcome(intake):
    intake = validate_intake(intake)
    if intake["status"] == "accepted":
        raise ValueError("Accepted research needs an evidence workflow.")
    if intake["status"] == "refused":
        reason = (
            "I cannot help select, manufacture or improve materials for weapons "
            "or for harming people. "
            "I can help with benign materials research, detection, protection, "
            "or remediation."
            if intake["reason_code"] in {"harmful_manufacture", "model_declined"}
            else (
                "I can help with public materials research, but cannot access "
                "private or paywalled data, perform wetlab actions, "
                "or fabricate evidence."
            )
        )
    else:
        reason = (
            "I need a little more context to frame a useful materials "
            "research question.\n\n"
            + "\n".join(f"{i}. {q}" for i, q in enumerate(intake["questions"], 1))
        )
    stage = "blocked" if intake["status"] == "refused" else "partial"
    return {
        "stage": stage,
        "answer": reason,
        "pi_summary": "",
        "technical_audit": "",
        "sources": [],
        "result": {
            "stage": stage,
            "intake": intake,
            "candidates": [],
            "reason": reason,
            "retrieval": {"status": "not_run"},
            "ranking": {"status": "not_run"},
        },
    }
