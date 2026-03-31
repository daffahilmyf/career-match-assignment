from pelgo.adapters.tools import tool_suite
from pelgo.domain.model.tool_schema import ResourceType, SkillResource


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_search_duckduckgo_keeps_real_mit_courses_only(monkeypatch):
    html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Focw.mit.edu%2F">MIT OpenCourseWare</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Focw.mit.edu%2Fsearch%2F">Search | MIT OpenCourseWare</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Focw.mit.edu%2Fcourses%2F6-004-computation-structures-spring-2017%2Fresources%2Fbasic-5-stage-pipeline%2F">Resource Fragment</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Focw.mit.edu%2Fcourses%2F6-824-distributed-computer-systems-engineering-spring-2006%2F">Distributed Systems</a>
    """

    monkeypatch.setattr(tool_suite, "_fetch_url", lambda *_args, **_kwargs: html)

    resources = tool_suite._search_duckduckgo(
        "distributed systems",
        timeout_seconds=5,
        domain="ocw.mit.edu",
        resource_type=ResourceType.course,
    )

    assert [str(resource.url) for resource in resources] == [
        "https://ocw.mit.edu/courses/6-824-distributed-computer-systems-engineering-spring-2006/"
    ]


def test_rerank_resources_prefers_relevant_pages(monkeypatch):
    page_text = {
        "https://example.com/": "Example company homepage with almost no learning content.",
        "https://docs.example.com/search/": "Search results for many topics.",
        "https://docs.example.com/ci-cd/getting-started/": "Continuous integration and continuous delivery pipelines guide with deployment stages and automation.",
    }

    monkeypatch.setattr(tool_suite, "_fetch_page_text", lambda url, _timeout: page_text.get(url, ""))

    resources = [
        SkillResource(title="Example", url=tool_suite._http_url("https://example.com/"), estimated_hours=8, type=ResourceType.doc),
        SkillResource(title="Search", url=tool_suite._http_url("https://docs.example.com/search/"), estimated_hours=8, type=ResourceType.doc),
        SkillResource(title="CI/CD Getting Started", url=tool_suite._http_url("https://docs.example.com/ci-cd/getting-started/"), estimated_hours=8, type=ResourceType.doc),
    ]

    ranked = tool_suite._rerank_resources("ci cd pipelines", resources, timeout_seconds=5)

    urls = [str(resource.url) for resource in ranked]
    assert urls[0] == "https://docs.example.com/ci-cd/getting-started/"
    assert "https://example.com/" not in urls
    assert "https://docs.example.com/search/" not in urls



def test_research_tool_balances_relevant_mit_and_docs(monkeypatch):
    monkeypatch.setattr(
        tool_suite,
        "_search_mit_ocw",
        lambda *_args, **_kwargs: [
            SkillResource(
                title="Distributed Systems",
                url=tool_suite._http_url("https://ocw.mit.edu/courses/6-824-distributed-computer-systems-engineering-spring-2006/"),
                estimated_hours=10,
                type=ResourceType.course,
            )
        ],
    )
    monkeypatch.setattr(
        tool_suite,
        "_search_duckduckgo",
        lambda *_args, **_kwargs: [
            SkillResource(
                title="Generic Docs",
                url=tool_suite._http_url("https://docs.example.com/distributed-systems/"),
                estimated_hours=8,
                type=ResourceType.doc,
            )
        ],
    )
    monkeypatch.setattr(tool_suite, "_fetch_page_text", lambda *_args, **_kwargs: "distributed systems course")

    tool = tool_suite.ResearchSkillResourcesTool(timeout_seconds=5, llm=None)
    output = tool(
        tool_suite.ResearchSkillResourcesInput(skill_name="distributed systems", seniority_context="senior")
    )

    urls = [str(resource.url) for resource in output.resources]
    assert urls[0] == "https://ocw.mit.edu/courses/6-824-distributed-computer-systems-engineering-spring-2006/"
    assert "https://docs.example.com/distributed-systems/" in urls
    assert output.relevance_score == 90



def test_search_mit_ocw_uses_structured_api_results(monkeypatch):
    payload = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "title": {"english": "Distributed Computer Systems Engineering"},
                        "url": "https://ocw.mit.edu/courses/6-824-distributed-computer-systems-engineering-spring-2006/",
                    }
                },
                {
                    "_source": {
                        "title": {"english": "OCW Search"},
                        "url": "https://ocw.mit.edu/search/",
                    }
                },
            ]
        }
    }

    monkeypatch.setattr(tool_suite.requests, "post", lambda *args, **kwargs: _FakeResponse(payload))

    resources = tool_suite._search_mit_ocw("distributed systems", timeout_seconds=5)

    assert [str(resource.url) for resource in resources] == [
        "https://ocw.mit.edu/courses/6-824-distributed-computer-systems-engineering-spring-2006/"
    ]
    assert resources[0].title == "Distributed Computer Systems Engineering"



def test_research_tool_prefers_practical_docs_when_mit_is_not_relevant(monkeypatch):
    monkeypatch.setattr(
        tool_suite,
        "_search_mit_ocw",
        lambda *_args, **_kwargs: [
            SkillResource(
                title="Introduction to World Music",
                url=tool_suite._http_url("https://ocw.mit.edu/courses/21m-030-introduction-to-world-music-fall-2006/"),
                estimated_hours=5,
                type=ResourceType.course,
            )
        ],
    )
    monkeypatch.setattr(
        tool_suite,
        "_search_duckduckgo",
        lambda *_args, **_kwargs: [
            SkillResource(
                title="CI/CD Pipelines",
                url=tool_suite._http_url("https://kubernetes.io/docs/concepts/cluster-administration/continuous-integration/"),
                estimated_hours=8,
                type=ResourceType.doc,
            )
        ],
    )

    def fake_fetch(url, _timeout):
        if "world-music" in url:
            return "music performance history and listening"
        return "continuous integration continuous delivery deployment pipeline automation kubernetes"

    monkeypatch.setattr(tool_suite, "_fetch_page_text", fake_fetch)

    tool = tool_suite.ResearchSkillResourcesTool(timeout_seconds=5, llm=None)
    output = tool(
        tool_suite.ResearchSkillResourcesInput(skill_name="ci cd pipelines", seniority_context="senior")
    )

    assert str(output.resources[0].url) == "https://kubernetes.io/docs/concepts/cluster-administration/continuous-integration/"
    assert all("world-music" not in str(resource.url) for resource in output.resources)



def test_search_mit_ocw_uses_run_slug_when_url_missing(monkeypatch):
    payload = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "title": "Machine Learning",
                        "runs": [
                            {"slug": "courses/6-867-machine-learning-fall-2006"}
                        ],
                    }
                }
            ]
        }
    }

    monkeypatch.setattr(tool_suite.requests, "post", lambda *args, **kwargs: _FakeResponse(payload))

    resources = tool_suite._search_mit_ocw("machine learning", timeout_seconds=5)

    assert [str(resource.url) for resource in resources] == [
        "https://ocw.mit.edu/courses/6-867-machine-learning-fall-2006/"
    ]
    assert resources[0].title == "Machine Learning"


def test_research_tool_respects_configurable_mit_course_limit(monkeypatch):
    mit_resources = [
        SkillResource(
            title=f"Course {index}",
            url=tool_suite._http_url(f"https://ocw.mit.edu/courses/course-{index}/"),
            estimated_hours=10,
            type=ResourceType.course,
        )
        for index in range(1, 6)
    ]
    monkeypatch.setattr(tool_suite, "_search_mit_ocw", lambda *_args, **_kwargs: mit_resources)
    monkeypatch.setattr(tool_suite, "_fetch_page_text", lambda *_args, **_kwargs: "machine learning statistical inference classification regression support vector machines bayesian networks course content")

    tool = tool_suite.ResearchSkillResourcesTool(timeout_seconds=5, llm=None, max_resources=4)
    output = tool(
        tool_suite.ResearchSkillResourcesInput(skill_name="machine learning", seniority_context="senior")
    )

    assert len(output.resources) == 4
