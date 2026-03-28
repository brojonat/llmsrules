---
name: openai-agents
description: Build multi-agent systems with the OpenAI Agents SDK, including tool definitions, handoffs, context management, and webhook validation. Use when creating OpenAI agent flows, defining tools, or handling agent handoffs in Python or Go.
---

# OpenAI Agents SDK

Build multi-agent systems with tool definitions, handoffs, context management, and tracing.

## Python Agent Flow

```python
from agents import (
    Agent, Runner, RunContextWrapper,
    function_tool, handoff, trace,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from pydantic import BaseModel


# Context shared across agents
class MyContext(BaseModel):
    user_name: str | None = None
    session_id: str | None = None


# Define tools with @function_tool
@function_tool(name_override="lookup_tool", description_override="Look up information.")
async def lookup_tool(question: str) -> str:
    return f"Answer to: {question}"


@function_tool
async def update_record(
    context: RunContextWrapper[MyContext], record_id: str, value: str
) -> str:
    """Update a record. Args: record_id, value."""
    context.context.session_id = record_id
    return f"Updated {record_id} to {value}"


# Define agents with handoffs
specialist = Agent[MyContext](
    name="Specialist",
    handoff_description="Handles specific tasks.",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    You are a specialist agent. Use your tools to help the customer.""",
    tools=[update_record],
)

triage = Agent[MyContext](
    name="Triage",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    You are a triage agent. Delegate to the appropriate specialist.""",
    handoffs=[specialist],
)

# Allow circular handoffs
specialist.handoffs.append(triage)


# Run the agent loop
async def main():
    current_agent = triage
    input_items = []
    context = MyContext()
    conversation_id = uuid.uuid4().hex[:16]

    while True:
        user_input = input("You: ")
        with trace("My workflow", group_id=conversation_id):
            input_items.append({"content": user_input, "role": "user"})
            result = await Runner.run(current_agent, input_items, context=context)

            for item in result.new_items:
                if isinstance(item, MessageOutputItem):
                    print(f"{item.agent.name}: {ItemHelpers.text_message_output(item)}")
                elif isinstance(item, HandoffOutputItem):
                    print(f"Handed off: {item.source_agent.name} -> {item.target_agent.name}")

            input_items = result.to_input_list()
            current_agent = result.last_agent
```

## Go Agent Flow

Uses [nlpodyssey/openai-agents-go](https://github.com/nlpodyssey/openai-agents-go):

```go
import (
    "github.com/nlpodyssey/openai-agents-go/agents"
    "github.com/nlpodyssey/openai-agents-go/agents/extensions/handoff_prompt"
    "github.com/nlpodyssey/openai-agents-go/tracing"
)

// Tools
type LookupArgs struct {
    Question string `json:"question"`
}

func Lookup(_ context.Context, args LookupArgs) (string, error) {
    return "Answer to: " + args.Question, nil
}

var LookupTool = agents.NewFunctionTool("lookup", "Look up information.", Lookup)

// Agents
var (
    Specialist = agents.New("Specialist").
        WithHandoffDescription("Handles specific tasks.").
        WithInstructions(handoff_prompt.PromptWithHandoffInstructions(`...`)).
        WithTools(LookupTool).
        WithModel("gpt-4o")

    Triage = agents.New("Triage").
        WithInstructions(handoff_prompt.PromptWithHandoffInstructions(`...`)).
        WithAgentHandoffs(Specialist).
        WithModel("gpt-4o")
)

func init() {
    Specialist.AgentHandoffs = append(Specialist.AgentHandoffs, Triage)
}

// Run
result, err := agents.RunInputs(ctx, Triage, inputItems)
```

## Key Patterns

- **Context**: Use a Pydantic BaseModel (Python) or context.Value (Go) for shared state across agents
- **Handoffs**: Agents delegate to each other; use `on_handoff` hooks for side effects
- **Tracing**: Wrap runs in `trace()` / `tracing.RunTrace()` with a `group_id` for conversation tracking
- **Tools**: Decorate with `@function_tool`; the SDK extracts args from the function signature
- **Circular handoffs**: Append handoffs after agent definition to avoid forward-reference issues

## Webhook Validation

```python
from fastapi import FastAPI, Request, Response
from openai import OpenAI, InvalidWebhookSignatureError

app = FastAPI()
client = OpenAI(webhook_secret=os.environ["OPENAI_WEBHOOK_SECRET"])

@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.body()
        headers = dict(request.headers)
        event = client.webhooks.unwrap(body, headers)

        if event.type == "response.completed":
            response = client.responses.retrieve(event.data.id)
            print("Response output:", response.output_text)

        return Response(status_code=200)
    except InvalidWebhookSignatureError:
        return Response(content="Invalid signature", status_code=400)
```
