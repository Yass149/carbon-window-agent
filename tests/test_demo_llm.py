import asyncio

from cwa.llm.demo import DemoLLM


def test_demo_does_not_mistake_charger_finding_for_carbon_lookup():
    response = asyncio.run(
        DemoLLM().create(
            "",
            [],
            [{"role": "user", "content": "Where can I charge in RG1?"}],
        )
    )

    answer = response.content[0]["input"]
    assert response.content[0]["name"] == "submit_answer"
    assert "cannot find charging stations" in answer["answer"]
    assert not answer.get("numbers_used", [])
