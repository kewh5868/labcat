"""Pure intake boundaries and closed outcomes; no evidence is
created."""

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
