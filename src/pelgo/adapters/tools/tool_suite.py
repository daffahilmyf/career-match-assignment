from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter

from pelgo.ports.persistence import JobRepositoryPort
from pelgo.domain.model.shared_types import ConfidenceLevel
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsInput,
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsInput,
    PrioritiseSkillGapsOutput,
    PrioritisedSkillGap,
    ResearchSkillResourcesInput,
    ResearchSkillResourcesOutput,
    ResourceType,
    ScoreCandidateInput,
    ScoreCandidateOutput,
    ScoreCandidateDimensionScores,
    SkillResource,
)
from pelgo.ports.llm import LLMClient
from pelgo.prompts.templates import EXTRACT_JD_PROMPT, ESTIMATE_HOURS_PROMPT, PRIORITISE_GAPS_PROMPT

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESOURCES = 3
MAX_RESOURCE_CANDIDATES = 8
MIT_SEARCH_API_URL = "https://open.mit.edu/api/v0/search/"

SENIORITY_TARGET_YEARS = {
    "intern": 0,
    "junior": 1,
    "mid": 3,
    "senior": 5,
    "lead": 7,
    "staff": 9,
    "principal": 12,
    "unspecified": 0,
}


class EstimateHoursResponse(BaseModel):
    hours: list[int] = Field(..., min_length=1)


class PrioritiseGapsResponse(BaseModel):
    ranked_skills: list[PrioritisedSkillGap]


HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def _http_url(url: str) -> HttpUrl:
    return HTTP_URL_ADAPTER.validate_python(url)


def _load_prompt(job_description: str) -> str:
    return EXTRACT_JD_PROMPT.replace("{{job_description}}", job_description)


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def _fetch_url(url: str, timeout_seconds: int) -> str:
    response = requests.get(url, timeout=timeout_seconds, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.text


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_+.#-]{1,}", text.lower())
    stop = {
        "and",
        "the",
        "with",
        "for",
        "you",
        "your",
        "will",
        "role",
        "job",
        "our",
        "are",
        "we",
        "a",
        "an",
        "to",
        "in",
        "of",
        "on",
        "as",
    }
    return [t for t in tokens if t not in stop]


def _extract_seniority(text: str) -> str:
    for level in ["intern", "junior", "mid", "senior", "lead", "staff", "principal"]:
        if re.search(rf"\b{level}\b", text, re.IGNORECASE):
            return level
    return "unspecified"


def _normalize_skill_list(skills: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        cleaned = re.sub(r"\(.*?\)", "", skill).strip().lower()
        if not cleaned:
            continue
        if any(token in cleaned for token in ["year", "years", "+", "experience"]):
            continue
        cleaned = re.sub(r"[^a-z0-9+.#-]+", " ", cleaned).strip()
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug_to_title(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    words = re.sub(r"[-_]+", " ", slug).split()
    return " ".join(word.capitalize() for word in words) if words else url


def _absolute_ocw_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return url
    if url.startswith("/"):
        return f"https://ocw.mit.edu{url}"
    if url.startswith("courses/"):
        return f"https://ocw.mit.edu/{url}"
    return None


def _mit_search_url(skill_name: str) -> str:
    return f"https://ocw.mit.edu/search/?q={quote_plus(skill_name)}"


def _mit_search_resource(skill_name: str) -> SkillResource:
    return SkillResource(
        title=f"MIT OCW Search: {skill_name}",
        url=_http_url(_mit_search_url(skill_name)),
        estimated_hours=6,
        type=ResourceType.course,
    )


def _is_course_landing_page(url: str, domain: str | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if domain and domain not in parsed.netloc:
        return False
    if not parsed.netloc.endswith("ocw.mit.edu"):
        return False
    if parsed.path in {"", "/", "/search", "/search/"}:
        return False
    path = parsed.path.rstrip("/")
    if "/resources/" in path or "/pages/" in path or "/sections/" in path:
        return False
    parts = [part for part in path.split("/") if part]
    if not parts or parts[0] != "courses":
        return False
    return len(parts) == 2


def _normalize_research_skill(skill_name: str) -> str:
    return re.sub(r"[^a-z0-9+.#-]+", " ", skill_name.lower()).strip()


def _is_generic_resource_page(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    if path in {"", "/", "/search", "/docs", "/documentation"}:
        return True
    if any(token in path for token in ["/search", "/tag/", "/tags/", "/category/", "/categories/"]):
        return True
    return False


def _dedupe_resources(resources: list[SkillResource], limit: int | None = None) -> list[SkillResource]:
    unique: list[SkillResource] = []
    seen: set[str] = set()
    for resource in resources:
        key = str(resource.url).rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(resource)
        if limit is not None and len(unique) >= limit:
            break
    return unique


def _resource_search_queries(skill_name: str) -> list[tuple[str, ResourceType]]:
    normalized = _normalize_research_skill(skill_name)
    return [
        (normalized, ResourceType.course),
        (f"{normalized} course", ResourceType.course),
        (f"{normalized} tutorial documentation", ResourceType.doc),
    ]


def _resource_quality_score(resource: SkillResource) -> int:
    url = str(resource.url).lower().rstrip("/")
    title = resource.title.lower()
    score = 0
    if _is_course_landing_page(url):
        score += 10
    if resource.type == ResourceType.doc:
        score += 8
    if resource.type == ResourceType.course:
        score += 6
    if any(token in url for token in ["docs.", "/guide", "/tutorial", "/learn", "/docs", "/documentation", "developer.", "learn."]):
        score += 12
    if any(token in title for token in ["introduction", "intro", "guide", "tutorial", "course"]):
        score += 4
    if any(domain in url for domain in ["wikipedia.org", "geeksforgeeks.org"]):
        score -= 50
    if _is_generic_resource_page(url):
        score -= 40
    return score


def _fetch_page_text(url: str, timeout_seconds: int) -> str:
    try:
        return _clean_text(_fetch_url(url, timeout_seconds))
    except requests.RequestException:
        return ""


def _score_resource_candidate(
    skill_name: str,
    resource: SkillResource,
    timeout_seconds: int,
    page_cache: dict[str, str],
) -> int:
    query_terms = set(_tokenize(skill_name))
    title_terms = set(_tokenize(resource.title))
    url_terms = set(_tokenize(str(resource.url)))
    score = _resource_quality_score(resource)
    score += 12 * len(query_terms.intersection(title_terms))
    score += 6 * len(query_terms.intersection(url_terms))

    page_text = page_cache.get(str(resource.url))
    if page_text is None:
        page_text = _fetch_page_text(str(resource.url), timeout_seconds)
        page_cache[str(resource.url)] = page_text
    if page_text:
        body_terms = set(_tokenize(page_text[:4000]))
        score += 4 * len(query_terms.intersection(body_terms))
        if len(body_terms) < 10:
            score -= 8
    return score


def _rank_resources(skill_name: str, resources: list[SkillResource], timeout_seconds: int) -> list[tuple[int, SkillResource]]:
    deduped = _dedupe_resources(resources)
    filtered = [resource for resource in deduped if not _is_generic_resource_page(str(resource.url))]
    candidates = filtered or deduped
    page_cache: dict[str, str] = {}
    scored = [
        (_score_resource_candidate(skill_name, resource, timeout_seconds, page_cache), index, resource)
        for index, resource in enumerate(candidates)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(score, resource) for score, _, resource in scored]


def _rerank_resources(skill_name: str, resources: list[SkillResource], timeout_seconds: int, limit: int = DEFAULT_MAX_RESOURCES) -> list[SkillResource]:
    return [resource for _, resource in _rank_resources(skill_name, resources, timeout_seconds)[:limit]]


def _select_balanced_resources(
    skill_name: str,
    mit_resources: list[SkillResource],
    web_resources: list[SkillResource],
    timeout_seconds: int,
    limit: int = DEFAULT_MAX_RESOURCES,
) -> list[SkillResource]:
    mit_ranked = _rank_resources(skill_name, mit_resources, timeout_seconds)
    web_ranked = _rank_resources(skill_name, web_resources, timeout_seconds)
    relevant_mit = [(score, resource) for score, resource in mit_ranked if score >= 25]

    selected: list[SkillResource] = []
    seen: set[str] = set()

    if relevant_mit:
        mit_resource = relevant_mit[0][1]
        selected.append(mit_resource)
        seen.add(str(mit_resource.url))

    for _, resource in web_ranked:
        key = str(resource.url)
        if key in seen:
            continue
        selected.append(resource)
        seen.add(key)
        if len(selected) >= limit:
            return selected

    for _, resource in relevant_mit[1:]:
        key = str(resource.url)
        if key in seen:
            continue
        selected.append(resource)
        seen.add(key)
        if len(selected) >= limit:
            return selected

    return selected


def _candidate_profile_payload(candidate_profile: str) -> dict[str, Any]:
    try:
        payload = json.loads(candidate_profile)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return {"summary": candidate_profile}


def _candidate_text(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("summary", "name", "email"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for key in ("skills", "experience", "education"):
        value = profile.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
    return "\n".join(parts)


def _candidate_skill_tokens(profile: dict[str, Any], candidate_text: str) -> set[str]:
    tokens = set(_tokenize(candidate_text))
    skills = profile.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, str):
                tokens.update(_tokenize(skill))
                tokens.add(skill.strip().lower())
    return {token for token in tokens if token}


def _candidate_years_experience(profile: dict[str, Any], candidate_text: str) -> int:
    years = profile.get("years_experience")
    if isinstance(years, int):
        return years
    if isinstance(years, str) and years.isdigit():
        return int(years)
    years_match = re.findall(r"(\d+)\+?\s+years?", candidate_text, re.IGNORECASE)
    return max([int(val) for val in years_match], default=0)


def _experience_fit_score(years_experience: int, experience_entries: list[str], seniority_level: str) -> int:
    target_years = SENIORITY_TARGET_YEARS.get(seniority_level, 0)
    if target_years <= 0:
        if years_experience > 0:
            return 100
        if experience_entries:
            return min(100, 40 + len(experience_entries) * 15)
        return 50

    if years_experience > 0:
        return min(100, int(round((years_experience / target_years) * 100)))

    if experience_entries:
        return min(100, 35 + len(experience_entries) * 20)
    return 20


def _unwrap_duckduckgo_url(url: str) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = f"https://duckduckgo.com{url}"
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        encoded = parse_qs(parsed.query).get("uddg", [])
        if encoded:
            return unquote(encoded[0])
    return url if parsed.scheme in {"http", "https"} else None


def _search_mit_ocw(skill_name: str, timeout_seconds: int, limit: int = DEFAULT_MAX_RESOURCES) -> list[SkillResource]:
    payload = {
        "from": 0,
        "size": max(limit * 3, limit),
        "post_filter": {
            "bool": {
                "must": [
                    {"term": {"object_type.keyword": "course"}},
                    {"term": {"offered_by": "OCW"}},
                ]
            }
        },
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": skill_name,
                            "fields": [
                                "title.english^3",
                                "short_description.english^2",
                                "full_description.english",
                                "topics",
                                "department_name",
                                "course_feature_tags",
                            ],
                        }
                    }
                ]
            }
        },
    }
    try:
        response = requests.post(
            MIT_SEARCH_API_URL,
            json=payload,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    raw_hits = data.get("hits", {}).get("hits", []) if isinstance(data, dict) else []
    hits = raw_hits if isinstance(raw_hits, list) else []
    resources: list[SkillResource] = []
    seen: set[str] = set()
    for hit in hits:
        source = hit.get("_source", {}) if isinstance(hit, dict) else {}
        if not isinstance(source, dict):
            source = {}
        raw_runs = source.get("runs", [])
        runs = raw_runs if isinstance(raw_runs, list) else []
        run_slug = None
        for run in runs:
            if isinstance(run, dict) and run.get("slug"):
                run_slug = run.get("slug")
                break
        raw_url = (
            run_slug
            or source.get("slug")
            or source.get("url")
            or source.get("course_url")
            or source.get("object_url")
            or source.get("path")
        )
        normalized = _absolute_ocw_url(raw_url)
        if not normalized:
            continue
        normalized = normalized.rstrip("/") + "/"
        if not _is_course_landing_page(normalized, domain="ocw.mit.edu"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        title_data = source.get("title")
        if isinstance(title_data, dict):
            title = title_data.get("english") or title_data.get("default") or _slug_to_title(normalized)
        else:
            title = str(title_data).strip() if title_data else _slug_to_title(normalized)
        resources.append(
            SkillResource(
                title=str(title).strip(),
                url=_http_url(normalized),
                estimated_hours=10,
                type=ResourceType.course,
            )
        )
        if len(resources) >= MAX_RESOURCE_CANDIDATES:
            break

    return resources


def _search_duckduckgo(
    query_text: str,
    timeout_seconds: int,
    domain: str | None = None,
    resource_type: ResourceType | None = None,
) -> list[SkillResource]:
    query = quote_plus(f"site:{domain} {query_text}" if domain else query_text)
    url = f"https://duckduckgo.com/html/?q={query}"
    try:
        html = _fetch_url(url, timeout_seconds)
    except requests.RequestException:
        return []

    matches = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
    resources: list[SkillResource] = []
    seen: set[str] = set()
    for raw_link, title in matches:
        resolved_link = _unwrap_duckduckgo_url(raw_link)
        if not resolved_link:
            continue
        normalized = resolved_link.rstrip("/") + "/"
        parsed = urlparse(normalized)
        if domain and domain not in parsed.netloc:
            continue
        if domain == "ocw.mit.edu" and not _is_course_landing_page(normalized, domain=domain):
            continue
        if domain != "ocw.mit.edu" and _is_generic_resource_page(normalized):
            continue
        cleaned_title = re.sub(r"<[^>]+>", "", title).strip()
        if not cleaned_title:
            cleaned_title = _slug_to_title(normalized)
        if normalized in seen:
            continue
        seen.add(normalized)
        inferred_type = resource_type or (ResourceType.doc if any(token in normalized for token in ["docs", "/doc", "/documentation", "guide", "tutorial"]) else ResourceType.course)
        resources.append(
            SkillResource(
                title=cleaned_title,
                url=_http_url(normalized),
                estimated_hours=8,
                type=inferred_type,
            )
        )
        if len(resources) >= MAX_RESOURCE_CANDIDATES:
            break
    return resources


@dataclass(frozen=True)
class ExtractJDRequirementsTool:
    name: ClassVar[str] = "extract_jd_requirements"
    input_model: ClassVar[type[ExtractJDRequirementsInput]] = ExtractJDRequirementsInput
    output_model: ClassVar[type[ExtractJDRequirementsOutput]] = ExtractJDRequirementsOutput
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    llm: LLMClient | None = None
    repository: JobRepositoryPort | None = None

    def __call__(self, payload: ExtractJDRequirementsInput) -> ExtractJDRequirementsOutput:
        if self.llm is None:
            raise RuntimeError("LLM client is required for JD extraction")
        text = payload.job_url_or_text
        if _is_url(text):
            if self.repository is not None:
                cached = self.repository.get_cached_jd(text)
                if cached is not None:
                    return ExtractJDRequirementsOutput.model_validate(cached.requirements_json)
            text = _fetch_url(text, self.timeout_seconds)
        cleaned = _clean_text(text)
        prompt = _load_prompt(cleaned)
        extracted = self.llm.complete_json(prompt, ExtractJDRequirementsOutput)
        output = ExtractJDRequirementsOutput(
            required_skills=_normalize_skill_list(extracted.required_skills),
            nice_to_have_skills=_normalize_skill_list(extracted.nice_to_have_skills),
            seniority_level=extracted.seniority_level,
            domain=extracted.domain.strip().lower(),
            responsibilities=extracted.responsibilities,
        )
        if _is_url(payload.job_url_or_text) and self.repository is not None:
            content_hash = _hash_content(cleaned)
            self.repository.upsert_cached_jd(payload.job_url_or_text, content_hash, output.model_dump())
        return output


@dataclass(frozen=True)
class ScoreCandidateTool:
    name: ClassVar[str] = "score_candidate_against_requirements"
    input_model: ClassVar[type[ScoreCandidateInput]] = ScoreCandidateInput
    output_model: ClassVar[type[ScoreCandidateOutput]] = ScoreCandidateOutput

    def __call__(self, payload: ScoreCandidateInput) -> ScoreCandidateOutput:
        profile = _candidate_profile_payload(payload.candidate_profile)
        candidate_text = _candidate_text(profile)
        required_skills = payload.requirements.required_skills
        candidate_skills = _candidate_skill_tokens(profile, candidate_text)
        required_set = {s.lower() for s in required_skills}
        matched = sorted(required_set.intersection(candidate_skills))
        gaps = sorted(required_set.difference(candidate_skills))
        coverage = len(matched) / max(1, len(required_set))

        jd_completeness_parts = [
            1 if payload.requirements.required_skills else 0,
            1 if payload.requirements.responsibilities else 0,
            1 if payload.requirements.seniority_level else 0,
            1 if payload.requirements.domain else 0,
        ]
        jd_completeness = sum(jd_completeness_parts) / len(jd_completeness_parts)

        candidate_seniority = _extract_seniority(candidate_text)
        jd_seniority = payload.requirements.seniority_level
        if candidate_seniority == jd_seniority:
            seniority_alignment = 1.0
        elif candidate_seniority == "unspecified" or jd_seniority == "unspecified":
            seniority_alignment = 0.5
        else:
            seniority_alignment = 0.0

        experience_entries = [str(item) for item in profile.get("experience", []) if item]
        years_experience = _candidate_years_experience(profile, candidate_text)
        experience_fit = _experience_fit_score(years_experience, experience_entries, jd_seniority)
        experience_alignment = experience_fit / 100

        domain_keywords = set(_tokenize(payload.requirements.domain))
        overlap = domain_keywords.intersection(candidate_skills)
        domain_overlap = len(overlap) / max(1, len(domain_keywords))

        confidence_score = (
            0.2 * jd_completeness
            + 0.35 * coverage
            + 0.25 * experience_alignment
            + 0.1 * seniority_alignment
            + 0.1 * domain_overlap
        )

        if confidence_score >= 0.75:
            confidence = ConfidenceLevel.high
        elif confidence_score >= 0.5:
            confidence = ConfidenceLevel.medium
        else:
            confidence = ConfidenceLevel.low

        skills_score = int(round(coverage * 100))
        seniority_score = int(round(seniority_alignment * 100))
        dimension_scores = ScoreCandidateDimensionScores(
            skills=skills_score,
            experience=experience_fit,
            seniority_fit=seniority_score,
        )
        overall = int(round((0.45 * skills_score) + (0.35 * experience_fit) + (0.20 * seniority_score)))

        return ScoreCandidateOutput(
            overall_score=overall,
            dimension_scores=dimension_scores,
            matched_skills=matched,
            gap_skills=gaps,
            confidence=confidence,
        )


@dataclass(frozen=True)
class PrioritiseSkillGapsTool:
    name: ClassVar[str] = "prioritise_skill_gaps"
    input_model: ClassVar[type[PrioritiseSkillGapsInput]] = PrioritiseSkillGapsInput
    output_model: ClassVar[type[PrioritiseSkillGapsOutput]] = PrioritiseSkillGapsOutput
    llm: LLMClient | None = None

    def __call__(self, payload: PrioritiseSkillGapsInput) -> PrioritiseSkillGapsOutput:
        context = payload.job_market_context.lower()
        if self.llm is not None and payload.gap_skills:
            gap_list = "\n".join(f"- {skill}" for skill in payload.gap_skills)
            prompt = PRIORITISE_GAPS_PROMPT.replace(
                "{{job_context}}", payload.job_market_context
            ).replace("{{gap_list}}", gap_list)
            try:
                response = self.llm.complete_json(prompt, PrioritiseGapsResponse)
                return PrioritiseSkillGapsOutput(ranked_skills=response.ranked_skills)
            except Exception:
                pass

        scored = []
        for skill in payload.gap_skills:
            score = 2 if skill.lower() in context else 1
            scored.append((skill, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        ranked = []
        for index, (skill, score) in enumerate(scored, start=1):
            gain = max(5, 15 - index)
            ranked.append(
                PrioritisedSkillGap(
                    skill=skill,
                    priority_rank=index,
                    estimated_match_gain_pct=gain,
                    rationale=(
                        "Higher impact based on job context" if score > 1 else "Baseline gap"
                    ),
                )
            )
        return PrioritiseSkillGapsOutput(ranked_skills=ranked)


@dataclass(frozen=True)
class ResearchSkillResourcesTool:
    name: ClassVar[str] = "research_skill_resources"
    input_model: ClassVar[type[ResearchSkillResourcesInput]] = ResearchSkillResourcesInput
    output_model: ClassVar[type[ResearchSkillResourcesOutput]] = ResearchSkillResourcesOutput
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    llm: LLMClient | None = None
    max_resources: int = DEFAULT_MAX_RESOURCES

    def __call__(self, payload: ResearchSkillResourcesInput) -> ResearchSkillResourcesOutput:
        normalized_query = _normalize_research_skill(payload.skill_name)
        mit_resources = _search_mit_ocw(normalized_query, self.timeout_seconds, limit=self.max_resources)

        web_resources: list[SkillResource] = []
        for query_text, resource_type in _resource_search_queries(normalized_query):
            if len(web_resources) >= MAX_RESOURCE_CANDIDATES:
                break
            web_resources.extend(
                _search_duckduckgo(
                    query_text,
                    self.timeout_seconds,
                    resource_type=resource_type,
                )
            )

        resources = _select_balanced_resources(
            payload.skill_name,
            mit_resources,
            web_resources,
            self.timeout_seconds,
            limit=self.max_resources,
        )
        if resources:
            relevance = 90 if any("ocw.mit.edu" in str(resource.url) for resource in resources) else 80
        else:
            resources = [_mit_search_resource(payload.skill_name)]
            relevance = 40

        if self.llm is not None and resources:
            resources_list = "\n".join(
                f"- {res.title} ({res.type})" for res in resources
            )
            prompt = ESTIMATE_HOURS_PROMPT.replace("{{skill_name}}", payload.skill_name).replace(
                "{{seniority_context}}", payload.seniority_context or "unspecified"
            ).replace("{{resources_list}}", resources_list)
            try:
                estimate = self.llm.complete_json(prompt, EstimateHoursResponse)
                if len(estimate.hours) == len(resources):
                    updated = []
                    for res, hours in zip(resources, estimate.hours):
                        updated.append(
                            SkillResource(
                                title=res.title,
                                url=res.url,
                                estimated_hours=max(2, min(40, int(hours))),
                                type=res.type,
                            )
                        )
                    resources = updated
            except Exception:
                pass

        return ResearchSkillResourcesOutput(resources=resources, relevance_score=relevance)
