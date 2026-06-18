"""Shared skill, role, and domain taxonomy for local heuristics."""

from __future__ import annotations

import re


SKILL_KEYWORDS: list[tuple[str, str, str]] = [
    ("python", "Python", "Programming Language"),
    ("javascript", "JavaScript", "Programming Language"),
    ("typescript", "TypeScript", "Programming Language"),
    ("java", "Java", "Programming Language"),
    ("go", "Go", "Programming Language"),
    ("rust", "Rust", "Programming Language"),
    ("c++", "C++", "Programming Language"),
    ("c/c++", "C/C++", "Programming Language"),
    ("c#", "C#", "Programming Language"),
    ("php", "PHP", "Programming Language"),
    ("c shell", "C Shell", "Programming Language"),
    ("react", "React", "Framework"),
    ("node.js", "Node.js", "Runtime"),
    ("node", "Node.js", "Runtime"),
    ("fastapi", "FastAPI", "Framework"),
    ("flask", "Flask", "Framework"),
    ("django", "Django", "Framework"),
    ("pydantic v2", "Pydantic v2", "Framework"),
    ("pydantic", "Pydantic", "Framework"),
    ("celery redbeat", "Celery RedBeat", "Framework"),
    ("celery", "Celery", "Framework"),
    ("asyncio", "Asyncio", "Framework"),
    ("pytorch", "PyTorch", "AI/ML"),
    ("ppo", "PPO", "AI/ML"),
    ("actor-critic", "Actor-Critic", "AI/ML"),
    ("generalized advantage estimation", "Generalized Advantage Estimation", "AI/ML"),
    ("transformer", "Transformers", "AI/ML"),
    ("transformers", "Transformers", "AI/ML"),
    ("nlp", "NLP", "AI/ML"),
    ("machine learning", "Machine Learning", "AI/ML"),
    ("reinforcement learning", "Reinforcement Learning", "AI/ML"),
    ("llm", "LLM", "AI/ML"),
    ("postgresql", "PostgreSQL", "Database"),
    ("postgres", "PostgreSQL", "Database"),
    ("jsonb", "JSONB", "Database"),
    ("mongodb", "MongoDB", "Database"),
    ("mongo", "MongoDB", "Database"),
    ("mysql", "MySQL", "Database"),
    ("sqlite", "SQLite", "Database"),
    ("redis", "Redis", "Database"),
    ("odbc", "ODBC", "Data Integration"),
    ("oauth2", "OAuth2", "Security"),
    ("oauth", "OAuth2", "Security"),
    ("mtls", "mTLS", "Security"),
    ("mTLS", "mTLS", "Security"),
    ("aes 256 gcm", "AES-256-GCM", "Security"),
    ("aes-256-gcm", "AES-256-GCM", "Security"),
    ("rbac", "RBAC", "Security"),
    ("audit logging", "Audit Logging", "Security"),
    ("azure key vault", "Azure Key Vault", "Cloud"),
    ("key vault", "Azure Key Vault", "Cloud"),
    ("azure container registry", "Azure Container Registry", "Cloud"),
    ("container registry", "Container Registry", "Cloud"),
    ("azure", "Azure", "Cloud"),
    ("aws", "AWS", "Cloud"),
    ("gcp", "GCP", "Cloud"),
    ("github actions", "GitHub Actions", "DevOps"),
    ("ci/cd", "CI/CD", "DevOps"),
    ("docker", "Docker", "Infrastructure"),
    ("kubernetes", "Kubernetes", "Infrastructure"),
    ("terraform", "Terraform", "Infrastructure"),
    ("linux", "Linux", "Infrastructure"),
    ("ubuntu", "Ubuntu", "Infrastructure"),
    ("rest api", "REST APIs", "API"),
    ("rest apis", "REST APIs", "API"),
    ("rest", "REST", "API"),
    ("graphql", "GraphQL", "API"),
    ("etl", "ETL", "Data Engineering"),
    ("data pipeline", "Data Pipelines", "Data Engineering"),
    ("data pipelines", "Data Pipelines", "Data Engineering"),
    ("distributed systems", "Distributed Systems", "Architecture"),
    ("distributed mutex", "Distributed Mutexes", "Architecture"),
    ("rate limit", "Rate Limit Handling", "Architecture"),
    ("scalable architecture", "Scalable Architecture", "Architecture"),
    ("scalable architectures", "Scalable Architecture", "Architecture"),
    ("containerization", "Containerization", "Infrastructure"),
    ("concurrency", "Concurrency", "Architecture"),
    ("static analysis", "Static Analysis", "Developer Tooling"),
    ("real-time dashboard", "Real-Time Dashboards", "Developer Tooling"),
]

ROLE_KEYWORDS = [
    "Software Engineer",
    "Software Engineer Intern",
    "Full Stack Engineer",
    "Backend Engineer",
    "Frontend Engineer",
    "Product Engineer",
    "Platform Engineer",
    "Cloud Engineer",
    "Infrastructure Engineer",
    "Data Engineer",
    "ETL Engineer",
    "Machine Learning Engineer",
    "AI Engineer",
    "Automation Engineer",
    "Design Automation Engineer",
    "Product Manager",
    "Designer",
]

DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "FinTech": ("fintech", "financial", "finance", "erp", "accounting"),
    "Data Engineering": ("etl", "data pipeline", "connector", "odbc", "jsonb"),
    "Backend Systems": ("api", "backend", "flask", "celery", "redis", "distributed"),
    "Cloud Infrastructure": ("azure", "docker", "container", "key vault", "auto scaling"),
    "Security": ("oauth", "mtls", "rbac", "audit", "encryption", "aes"),
    "AI/ML": ("machine learning", "pytorch", "reinforcement learning", "nlp", "transformer", "llm"),
    "Developer Tooling": ("automation tooling", "static analysis", "code reviews", "dashboard"),
    "Hardware Automation": ("hardware design", "design automation", "validation work"),
    "SaaS": ("saas", "multi tenant", "multi-tenant"),
}

ROLE_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "data engineer": (
        "data engineer",
        "etl",
        "data pipeline",
        "connector",
        "warehouse",
        "odbc",
    ),
    "backend engineer": (
        "backend",
        "api",
        "platform",
        "distributed systems",
        "flask",
        "celery",
        "redis",
    ),
    "platform engineer": (
        "platform engineer",
        "infrastructure",
        "cloud",
        "docker",
        "kubernetes",
        "azure",
        "devops",
    ),
    "machine learning engineer": (
        "machine learning",
        "ml engineer",
        "ai engineer",
        "pytorch",
        "nlp",
        "reinforcement learning",
    ),
    "automation engineer": (
        "automation engineer",
        "design automation",
        "developer tooling",
        "static analysis",
        "validation",
    ),
    "software engineer": (
        "software engineer",
        "developer",
        "full stack",
        "backend",
        "frontend",
        "api engineer",
        "product engineer",
    ),
    "product manager": ("product manager", "program manager", "product owner"),
}


def _normalize_skill(skill: str) -> str:
    """Strip punctuation/case so variants compare equal ('Node.js' -> 'nodejs')."""
    return re.sub(r"[.\-/]", "", str(skill).strip().lower())


# Built once at import: (normalized_keyword, display, category), longest
# keyword first so the most specific match wins during containment.
_SKILL_LOOKUP: list[tuple[str, str, str]] = sorted(
    (
        (_normalize_skill(keyword), display, category)
        for keyword, display, category in SKILL_KEYWORDS
    ),
    key=lambda row: len(row[0]),
    reverse=True,
)


def canonical_skill(skill: str) -> tuple[str, str] | None:
    """Resolve a free-form skill string to its (display name, category).

    Returns None for unknown skills. An exact normalized match wins first
    (so 'java' and 'javascript' never collide); otherwise the longest known
    keyword contained in — or containing — the skill is used, guarded by a
    3-char floor to avoid spurious substring hits.
    """
    norm = _normalize_skill(skill)
    if not norm:
        return None
    for keyword, display, category in _SKILL_LOOKUP:
        if keyword == norm:
            return display, category
    if len(norm) < 3:
        return None
    for keyword, display, category in _SKILL_LOOKUP:
        if len(keyword) >= 3 and (keyword in norm or norm in keyword):
            return display, category
    return None


def contains_keyword(text: str, keyword: str) -> bool:
    """Match a keyword without substring false positives."""
    normalized = keyword.lower()
    pattern = re.compile(
        r"(?<![A-Za-z0-9+#])" + re.escape(normalized) + r"(?![A-Za-z0-9+#])",
        re.IGNORECASE,
    )
    return bool(pattern.search(text.lower()))


def extract_skill_hits(text: str) -> list[tuple[str, str]]:
    """Return display skill names and categories found in text."""
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for keyword, display, category in SKILL_KEYWORDS:
        canonical = display.lower()
        if canonical in seen:
            continue
        if display == "Pydantic" and "pydantic v2" in seen:
            continue
        if display == "REST" and "rest apis" in seen:
            continue
        if contains_keyword(text, keyword):
            hits.append((display, category))
            seen.add(canonical)
    return hits


def extract_domains(text: str) -> list[str]:
    """Infer broad experience domains from text."""
    lower = text.lower()
    domains: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            domains.append(domain)
    return domains


def infer_role_family(text: str) -> str | None:
    """Infer a role family from title or description text."""
    lower = text.lower()
    for family, keywords in ROLE_FAMILY_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return family
    return None
