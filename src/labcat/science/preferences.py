"""Bounded composition/search preferences, never evidence or measured
properties."""

import re
from fractions import Fraction

ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu "
    "Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs "
    "Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg "
    "Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db "
    "Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)
UNSUPPORTED_CLASSES = frozenset(
    {
        "polymers",
        "mofs",
        "polymer_matrix_composites",
        "ceramic_matrix_composites",
        "biomaterials",
        "elastomers",
        "liquid_crystals",
        "thermosets",
        "thermoplastics",
        "high_entropy_alloys",
        "perovskites",
        "perovskitoids",
        "semiconductor_nanocrystals",
        "organic_electronic_materials",
        "two_dimensional_materials",
    }
)
COMPOUND_CLASS_ELEMENTS = {
    "oxide": "O",
    "nitride": "N",
    "carbide": "C",
    "sulfide": "S",
    "sulphide": "S",
    "boride": "B",
    "phosphide": "P",
    "silicide": "Si",
    "selenide": "Se",
    "telluride": "Te",
    "fluoride": "F",
    "chloride": "Cl",
    "bromide": "Br",
    "iodide": "I",
    "hydride": "H",
}
_COMPOUND_CLASSES = re.compile(r"\b(?:" + "|".join(COMPOUND_CLASS_ELEMENTS) + r")s?\b")
_EXAMPLE_CUES = re.compile(
    r"\b(?:examples?|such as|including|like|for instance|among others|"
    r"not limited to|beyond|alternatives to)\b|\be\.g\."
)


def _negated_class(text, start):
    return bool(
        re.search(
            r"(?:\b(?:not|non|exclude|excluding|except|without)|"
            r"instead of|rather than)[ -]+$",
            text[max(0, start - 40) : start],
        )
    )


def _class_preferences(prompt, material_class):
    """Closed class boundaries; alternative classes cannot become an AND
    query."""
    text = prompt.lower()
    compound = list(_COMPOUND_CLASSES.finditer(text))
    metals = list(re.finditer(r"\b(?:metals?|alloys?|metallic)\b", text))
    semiconductors = list(re.finditer(r"\bsemiconductors?\b", text))
    nonspecific = bool(re.search(r"\b(?:ceramics?|halides?|chalcogenides?)\b", text))
    explicit = bool(compound or metals or semiconductors or nonspecific)
    elements = {
        COMPOUND_CLASS_ELEMENTS[match[0].removesuffix("s")]
        for match in compound
        if not _negated_class(text, match.start())
    }
    metal = any(not _negated_class(text, match.start()) for match in metals)
    semiconductor = any(
        not _negated_class(text, match.start()) for match in semiconductors
    )
    # "Metal oxides" names a composition class, not observed metallicity.
    if compound:
        metal = any(
            match[0] == "metallic" and not _negated_class(text, match.start())
            for match in metals
        )
    if not explicit:
        if material_class in {"oxide_dielectrics", "ceramic_oxides"}:
            elements = {"O"}
        elif isinstance(material_class, str):
            element = COMPOUND_CLASS_ELEMENTS.get(material_class.removesuffix("s"))
            if element:
                elements = {element}
        metal = material_class == "metals_metal_alloys"
        semiconductor = material_class == "semiconductors"
    ambiguous = len(elements) > 1 or (metal and semiconductor)
    # Generic halides/chalcogenides and exclusions alone need a disjunction or
    # richer class evidence that these composition filters do not represent.
    ambiguous |= explicit and not (elements or metal or semiconductor)
    if ambiguous:
        return {}, explicit, True
    filters = {"elements": next(iter(elements))} if elements else {}
    if metal or semiconductor:
        filters["is_metal"] = "true" if metal else "false"
    return filters, explicit, False


def _composition_scope(prompt):
    """A necessary composition screen, not proof of alloy phase or
    processing."""
    text = prompt.casefold()
    alloys = list(re.finditer(r"\b(?:metal(?:lic)?[ -]+)?alloys?\b", text))
    elemental = list(
        re.finditer(
            r"\b(?:(?:pure|elemental|unalloyed|single[ -]element)[ -]+"
            r"(?:transition[ -]+)?metals?|metals?[ -]+(?:that[ -]+are[ -]+)?"
            r"(?:pure|elemental|unalloyed))\b",
            text,
        )
    )

    def negated(match):
        return _negated_class(text, match.start()) or bool(
            re.search(
                r"\b(?:no|avoid|avoiding|omit|omitting|"
                r"(?:do not|don't) (?:use|include|select))\s+$",
                text[max(0, match.start() - 60) : match.start()],
            )
        )

    alloy = any(
        not negated(match) and not re.match(r"[ -]free\b", text[match.end() :])
        for match in alloys
    )
    pure = any(not negated(match) for match in elemental)
    # Explicit comparisons of pure metals and alloys need both populations.
    # A class mentioned only as a negation never reverses a source constraint.
    if alloy == pure:
        return None
    return "multi_element" if alloy else "single_element"


def matches_composition_scope(formula, scope):
    """Check an independently retrieved formula against an internal
    preference."""
    count = len(validate_formula(formula))
    if scope == "multi_element":
        return count >= 2
    if scope == "single_element":
        return count == 1
    if scope is None:
        return True
    raise ValueError("Unsupported composition scope preference.")


def _restricts_composition(prompt, start):
    """Recognize an explicit comparison/list, not 'only public
    sources'."""
    prefix = prompt[max(0, start - 200) : start].lower()
    return bool(
        re.search(
            r"\b(?:compare|contrast|comparison of|comparison between|only|"
            r"restrict(?:ed)?(?: the)?(?: search| results| candidates)? to|"
            r"limit(?:ed)?(?: the)?(?: search| results| candidates)? to|"
            r"focus(?:ed)?(?: only)? on)\s*"
            r"(?:(?:the|following|these|listed|specified|materials?|compounds?|"
            r"formulas?|compositions?|systems?|candidates?)\s*[: ,]?\s*)*$",
            prefix,
        )
        or re.search(r"\b(?:versus|vs\.?)\s+", prompt[start:].lower())
        or re.match(
            r"[A-Z][A-Za-z0-9().-]{0,119}"
            r"(?:\s*(?:,|and|or)\s*[A-Z][A-Za-z0-9().-]{0,119})*\s+only\b",
            prompt[start:],
        )
    )


def _broad_discovery(prompt, start):
    text = prompt.lower()
    if _restricts_composition(prompt, start):
        return False
    if _EXAMPLE_CUES.search(text):
        return True
    prefix = text[:start]
    explicit_class = _class_preferences(prefix, None)[1]
    return bool(
        re.search(
            r"\b(?:find|discover|identify|suggest|recommend|search|explore|survey)\b",
            prefix,
        )
        and (
            explicit_class
            or re.search(r"\b(?:candidates?|alternatives|broad|range)\b", prefix)
        )
    )


def validate_formula(formula):
    """Accept bounded elemental formula notation; reject prose and fake
    symbols."""
    if not isinstance(formula, str) or not 1 <= len(formula) <= 120:
        raise ValueError("Source formula is missing or malformed.")
    tokens = re.findall(r"[A-Z][a-z]?|[0-9]+(?:\.[0-9]+)?|[()]", formula)
    if "".join(tokens) != formula:
        raise ValueError("Source formula contains unsupported notation.")
    elements, stack = set(), [0]
    can_count = False
    for token in tokens:
        if token == "(":
            if len(stack) >= 5:
                raise ValueError("Source formula nesting exceeds the limit.")
            stack.append(0)
            can_count = False
        elif token == ")":
            if len(stack) == 1 or not stack.pop():
                raise ValueError("Source formula grouping is malformed.")
            stack[-1] += 1
            can_count = True
        elif token[0].isdigit():
            if not can_count or not 0 < float(token) <= 1_000_000:
                raise ValueError("Source formula count is malformed.")
            can_count = False
        else:
            if token not in ELEMENTS:
                raise ValueError("Source formula uses an unsupported element symbol.")
            elements.add(token)
            stack[-1] += 1
            can_count = True
    if len(stack) != 1 or not stack[0]:
        raise ValueError("Source formula grouping is malformed.")
    return sorted(elements)


def composition_key(formula):
    """Ratio key for matching hints against independently returned
    formulas."""
    validate_formula(formula)
    tokens = re.findall(r"[A-Z][a-z]?|[0-9]+(?:\.[0-9]+)?|[()]", formula)
    stack, index = [{}], 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == "(":
            stack.append({})
            continue
        group = stack.pop() if token == ")" else {token: Fraction(1)}
        count = Fraction(1)
        if index < len(tokens) and tokens[index][0].isdigit():
            count = Fraction(tokens[index])
            index += 1
        for element, number in group.items():
            stack[-1][element] = stack[-1].get(element, Fraction(0)) + number * count
    values = stack[0]
    divisor = values[min(values)]
    return tuple((element, values[element] / divisor) for element in sorted(values))


def source_search_context(prompt, material_class=None, *, semantic_scope=None):
    """Resolve composition hints from exact requested targets, never
    surroundings.

    Semantic intake is a preference classification, not material
    evidence. Its span binding is rechecked here before it can narrow
    any source query.
    """
    if semantic_scope is None:
        return prompt, material_class, None
    from labcat.research_intent import validate_scope

    scope = validate_scope(semantic_scope, prompt)
    selected_class = scope["material_class"]
    selected_class = None if selected_class in {"unknown", "custom"} else selected_class
    target = scope["target_text"]
    # Keep broad-discovery preferences without reintroducing environmental
    # chemicals. The context outside material spans can qualify examples, but
    # it never supplies formulas, elements or source property values.
    preference_text = prompt
    for role in ("application_spans", "environment_spans", "processing_spans"):
        for span in scope[role]:
            preference_text = preference_text.replace(span, " " * len(span))
    hints = derive_search_filters(target, selected_class)
    identities = set(hints.get("formula", "").split(",")) - {""}
    if hints.get("chemsys"):
        identities.update(
            match[0] for match in re.finditer(r"[A-Z][a-z]?(?:-[A-Z][a-z]?)+", target)
        )
    identity_positions = [
        prompt.index(span) + span.index(identity)
        for identity in identities
        for span in scope["target_spans"]
        if identity in span
    ]
    if identity_positions and _broad_discovery(
        preference_text, min(identity_positions)
    ):
        target = "examples: " + target
    return (
        target,
        selected_class,
        scope["identity_scope"],
    )


def supports_bulk_search(prompt, material_class=None, *, semantic_scope=None):
    """These classes need class/scale evidence that bulk composition
    cannot prove."""
    prompt, material_class, identity_scope = source_search_context(
        prompt, material_class, semantic_scope=semantic_scope
    )
    if not scalar_scope_resolved(prompt, material_class, identity_scope):
        return False
    if requires_unmapped_scope_evidence(prompt, material_class):
        return False
    if re.search(
        r"\b(?:polymers?|composites?|biomaterials?|elastomers?|thermosets?|"
        r"thermoplastics?|mofs?|metal[ -]organic|liquid[ -]crystals?|"
        r"high[ -]entropy|perovskites?|perovskitoids?|quantum[ -]dots?|"
        r"nanocrystals?)\b",
        prompt.lower(),
    ):
        return False
    _, explicit, ambiguous = _class_preferences(prompt, material_class)
    if material_class in UNSUPPORTED_CLASSES and not explicit:
        return False
    if ambiguous:
        filters = derive_search_filters(prompt, material_class)
        return bool(filters.get("formula") or filters.get("chemsys"))
    return True


def scalar_scope_resolved(prompt, material_class, identity_scope):
    """A semantic uncertainty cannot authorize a generic bulk
    population."""
    if identity_scope is None:
        return True  # Preserve the legacy caller's separate capability checks.
    if identity_scope in {"molecular", "nanoscale"}:
        return False
    filters = derive_search_filters(prompt, material_class)
    identity_keys = ("formula", "chemsys", "elements", "is_metal")
    if not any(filters.get(key) for key in identity_keys):
        return False
    if material_class is None and (
        identity_scope != "bulk" or not any(filters.get(key) for key in identity_keys)
    ):
        return False
    if _class_preferences(prompt, material_class)[2]:
        return bool(filters.get("formula") or filters.get("chemsys"))
    return True


def requires_unmapped_scope_evidence(
    prompt, material_class=None, *, semantic_scope=None
):
    """Reject molecular/scale claims absent from the current scalar
    adapters.

    These are request boundaries, not classifications of source records.
    A bulk formula or a perovskite label cannot prove molecular
    identity, confinement, particle size or inorganic connectivity.
    Thin-film processing alone does not make a dimensionality claim.
    """
    prompt, material_class, identity_scope = source_search_context(
        prompt, material_class, semantic_scope=semantic_scope
    )
    if identity_scope in {"molecular", "nanoscale"} or material_class in {
        "organic_electronic_materials",
        "semiconductor_nanocrystals",
        "two_dimensional_materials",
    }:
        return True
    text = " ".join(re.findall(r"[^\W_]+", prompt.casefold()))
    molecular = (
        r"\b(?:organic (?:semiconductors?|photovoltaics?|solar cells?|"
        r"electronic(?:s| materials?)?|optoelectronic(?:s| materials?)?|"
        r"donors?|acceptors?|absorbers?|molecules?|crystals?)|"
        r"organic materials? (?:for |in )?(?:photovoltaics?|solar cells?|"
        r"optoelectronics?|electronics?)|"
        r"molecular (?:donors?|acceptors?|semiconductors?|photovoltaics?|"
        r"electronic(?:s| materials?)?|crystals?)|small molecules?|opvs?)\b"
    )
    nanoscale = (
        r"\b(?:quantum dots?|qds?|nano ?(?:crystals?|particles?|dots?|"
        r"wires?|tubes?|sheets?))\b"
    )
    dimensional = (
        r"\b(?:[0-3] ?d|(?:zero|one|two|three|low) dimensional|"
        r"layered|monolayers?|few layers?)\b"
    )
    return any(
        re.search(pattern, text) for pattern in (molecular, nanoscale, dimensional)
    )


def derive_search_filters(prompt, material_class=None, *, semantic_scope=None):
    """Extract only formula/class hints; no user numbers become property
    values."""
    prompt, material_class, _ = source_search_context(
        prompt, material_class, semantic_scope=semantic_scope
    )
    if not isinstance(prompt, str) or len(prompt) > 20_000:
        raise ValueError("Search preferences exceed the supported size.")
    filters = {}
    systems = list(
        re.finditer(
            r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?)(?:-[A-Z][a-z]?)+(?![A-Za-z0-9])", prompt
        )
    )
    systems = [match for match in systems if set(match[0].split("-")) <= ELEMENTS]
    if systems and not _broad_discovery(prompt, systems[0].start()):
        filters["chemsys"] = ",".join(
            sorted({"-".join(sorted(set(s[0].split("-")))) for s in systems})[:5]
        )
    elif not systems:
        formulas = []
        positions = []
        for match in re.finditer(
            r"(?<![A-Za-z0-9/])[A-Z][A-Za-z0-9().]{0,119}(?![A-Za-z0-9])", prompt
        ):
            token = match[0].rstrip(".")
            if token in {
                "I",
                "As",
                "In",
                "He",
                "At",
                "No",
                "Am",
                "Be",
            } and not re.search(
                r"\b(?:element|formula|metal|containing)\s+" + re.escape(token) + r"\b",
                prompt,
            ):
                continue
            try:
                validate_formula(token)
            except ValueError:
                continue
            if token not in formulas:
                formulas.append(token)
                positions.append(match.start())
        if formulas and not _broad_discovery(prompt, positions[0]):
            filters["formula"] = ",".join(formulas[:5])
    text = prompt.lower()
    if not filters:
        filters.update(_class_preferences(prompt, material_class)[0])
    if scope := _composition_scope(prompt):
        filters["composition_scope"] = scope
    if re.search(r"\bdielectric\w*\b|\bpermittivity\b", text):
        filters["has_props"] = "dielectric"
    return filters


def validate_search_filters(filters):
    if filters is None:
        return {}
    if not isinstance(filters, dict) or set(filters) - {
        "formula",
        "chemsys",
        "elements",
        "is_metal",
        "has_props",
        "material_ids",
        "entry_ids",
        "exclude_elements",
        "prefer_simple",
        "composition_scope",
    }:
        raise ValueError("Unsupported material search filters.")
    for name, value in filters.items():
        if not isinstance(value, str) or not 0 < len(value) <= 600:
            raise ValueError("Invalid material search filter.")
        if name in {"material_ids", "entry_ids"}:
            entries = value.split(",")
            pattern = (
                r"mp-[0-9]{1,10}" if name == "material_ids" else r"[A-Za-z0-9_-]{1,80}"
            )
            if (
                len(entries) > 6
                or len(set(entries)) != len(entries)
                or any(not re.fullmatch(pattern, entry) for entry in entries)
            ):
                raise ValueError("Invalid prior material identity hint.")
        elif name == "formula":
            entries = value.split(",")
            if len(entries) > 5:
                raise ValueError("Too many formula search hints.")
            for entry in entries:
                validate_formula(entry)
        elif name == "chemsys":
            entries = value.split(",")
            if len(entries) > 5 or any(
                not set(entry.split("-")) <= ELEMENTS for entry in entries
            ):
                raise ValueError("Invalid chemical-system search hint.")
        elif (
            name in {"elements", "exclude_elements"}
            and not set(value.split(",")) <= ELEMENTS
        ):
            raise ValueError("Invalid element search hint.")
        elif name == "is_metal" and value not in {"true", "false"}:
            raise ValueError("Invalid metallicity preference.")
        elif name == "prefer_simple" and value != "true":
            raise ValueError("Unsupported composition sampling preference.")
        elif name == "composition_scope" and value not in {
            "multi_element",
            "single_element",
        }:
            raise ValueError("Unsupported composition scope preference.")
        elif name == "has_props" and value not in {"dielectric", "elasticity"}:
            raise ValueError("Unsupported property-availability preference.")
    return filters.copy()
