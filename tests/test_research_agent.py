from src.agents.research_agent.agent import ResearchAgent

agent = ResearchAgent()

research = agent.research("Top 10 Hidden Underground Cities")

print("Topic:", research.topic)
print("Summary:", research.research_summary)
print("Status:", research.status)
print("Facts:", len(research.key_facts))
print("Sources:", len(research.sources))

assert research.topic == "Top 10 Hidden Underground Cities"
assert research.status.value == "approved"

print("Research Agent test completed successfully.")
