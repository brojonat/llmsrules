---
name: temporal-python
description: Build Temporal applications in Python using the temporalio SDK. Use when creating workflows, activities, workers, clients, signals, queries, updates, child workflows, timers, retry policies, saga/compensation patterns, testing, or any durable execution pattern in Python.
---

# Temporal Python SDK (temporalio)

Build durable, fault-tolerant distributed applications in Python. Temporal guarantees workflow completion even through process crashes, network failures, and server outages.

## Installation

```bash
pip install temporalio
```

Requires Python >= 3.9. The SDK is a single package with no heavy dependencies.

## Core Concepts

- **Workflow**: A durable function (defined as a class) that orchestrates activities and other workflows. Must be deterministic -- no random, no real I/O, no system time.
- **Activity**: A normal function (sync or async) that performs side effects -- API calls, database queries, file I/O.
- **Worker**: A process that polls a task queue and executes workflows and activities.
- **Client**: Connects to the Temporal server to start, signal, query, and cancel workflows.
- **Task Queue**: A named queue that routes work to workers. Workflows and activities are assigned to task queues.

## Project Structure

```
my_temporal_app/
    workflows.py       # Workflow definitions
    activities.py      # Activity definitions
    worker.py          # Worker startup
    client.py          # Client code (start/signal/query workflows)
    models.py          # Shared dataclasses for inputs/outputs
    tests/
        conftest.py    # Test fixtures (WorkflowEnvironment)
        test_workflows.py
        test_activities.py
```

## Imports

```python
# Workflow module -- used inside workflow definitions
from temporalio import workflow

# Activity module -- used inside activity definitions
from temporalio import activity

# Client -- used to connect to Temporal and interact with workflows
from temporalio.client import Client

# Worker -- used to run workflows and activities
from temporalio.worker import Worker

# Common types -- RetryPolicy, SearchAttributes, etc.
from temporalio.common import RetryPolicy

# Exceptions
from temporalio.exceptions import (
    ApplicationError,       # Raise from activities/workflows for business errors
    ActivityError,          # Caught in workflows when an activity fails
    ChildWorkflowError,     # Caught when a child workflow fails
    CancelledError,         # Caught when workflow/activity is cancelled
    FailureError,           # Base class for all failure errors
)

# Testing
from temporalio.testing import WorkflowEnvironment, ActivityEnvironment
```

### Workflow Sandbox Imports

Workflow code runs in a sandbox that intercepts non-deterministic calls. When importing third-party modules or your own activity/model modules inside a workflow file, use the pass-through pattern:

```python
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from my_app.activities import my_activity
    from my_app.models import MyInput, MyOutput
```

This prevents the sandbox from interfering with imports that are only used as type references or activity references.

## Data Models

Temporal strongly encourages using a single dataclass parameter for activities and workflows instead of multiple parameters. This allows backwards-compatible field additions.

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrderInput:
    order_id: str
    customer_name: str
    amount: float
    currency: str = "USD"

@dataclass
class OrderResult:
    order_id: str
    status: str
    confirmation_number: Optional[str] = None
```

## Activity Definitions

### Async Activity (runs in the worker event loop)

```python
from temporalio import activity

@activity.defn
async def process_payment(input: PaymentInput) -> PaymentResult:
    activity.logger.info("Processing payment for order %s", input.order_id)
    result = await payment_gateway.charge(input.amount, input.card_token)
    return PaymentResult(transaction_id=result.id, status="completed")
```

### Sync Activity (requires a thread pool executor on the worker)

```python
import time
from temporalio import activity

@activity.defn
def send_email(input: EmailInput) -> None:
    activity.logger.info("Sending email to %s", input.recipient)
    # Blocking I/O is fine in sync activities
    smtp_client.send(to=input.recipient, subject=input.subject, body=input.body)
```

### Activity with Heartbeating (for long-running activities)

```python
import time
from temporalio import activity

@activity.defn
def process_large_dataset(input: DatasetInput) -> DatasetResult:
    rows_processed = 0
    for batch in read_batches(input.file_path):
        # Heartbeat to tell the server this activity is still alive.
        # If heartbeat_timeout passes without a heartbeat, the server
        # considers the activity failed and retries it.
        activity.heartbeat(rows_processed)
        process_batch(batch)
        rows_processed += len(batch)
    return DatasetResult(total_rows=rows_processed)
```

When the activity is retried, you can retrieve the last heartbeat details:

```python
@activity.defn
def resumable_activity(input: ProcessInput) -> ProcessResult:
    # On retry, pick up from where we left off
    start_index = 0
    if activity.info().heartbeat_details:
        start_index = activity.info().heartbeat_details[0]

    for i in range(start_index, len(input.items)):
        activity.heartbeat(i)
        process_item(input.items[i])

    return ProcessResult(processed=len(input.items))
```

### Activity as a Class Method (for dependency injection)

```python
from temporalio import activity

class MyActivities:
    def __init__(self, db_client: DatabaseClient) -> None:
        self.db_client = db_client

    @activity.defn
    async def fetch_record(self, input: FetchInput) -> Record:
        return await self.db_client.get(input.record_id)

    @activity.defn
    async def save_record(self, input: SaveInput) -> None:
        await self.db_client.save(input.record)
```

When registering with the worker, instantiate the class and pass the bound methods:

```python
my_activities = MyActivities(db_client)
worker = Worker(
    client,
    task_queue="my-task-queue",
    workflows=[MyWorkflow],
    activities=[my_activities.fetch_record, my_activities.save_record],
)
```

When calling from a workflow, use `workflow.execute_activity_method`:

```python
result = await workflow.execute_activity_method(
    MyActivities.fetch_record,
    FetchInput(record_id="123"),
    start_to_close_timeout=timedelta(seconds=10),
)
```

### Custom Activity Name

```python
@activity.defn(name="custom-activity-name")
async def my_activity(input: MyInput) -> MyOutput:
    ...
```

### Dynamic Activity (catch-all for unregistered activity types)

```python
from typing import Sequence
from temporalio.common import RawValue

@activity.defn(dynamic=True)
async def dynamic_activity(args: Sequence[RawValue]) -> str:
    arg1 = activity.payload_converter().from_payload(args[0].payload, MyDataClass)
    activity_type = activity.info().activity_type
    return f"Dynamic activity {activity_type} received: {arg1}"
```

### Async Activity Completion (complete from outside the activity function)

```python
from temporalio import activity

class MyProcessor:
    def __init__(self, client: Client) -> None:
        self.client = client

    @activity.defn
    async def start_processing(self, input: ProcessInput) -> str:
        task_token = activity.info().task_token
        # Hand off to external system, passing the task_token
        await self.external_queue.send(task_token, input)
        # Signal that this activity will be completed externally
        activity.raise_complete_async()

    async def complete_from_external(self, task_token: bytes, result: str) -> None:
        handle = self.client.get_async_activity_handle(task_token=task_token)
        await handle.complete(result)

    async def fail_from_external(self, task_token: bytes, error: Exception) -> None:
        handle = self.client.get_async_activity_handle(task_token=task_token)
        await handle.fail(error)

    async def heartbeat_from_external(self, task_token: bytes) -> None:
        handle = self.client.get_async_activity_handle(task_token=task_token)
        await handle.heartbeat()
```

### Activity Info

Access activity metadata inside an activity:

```python
@activity.defn
async def my_activity(input: MyInput) -> MyOutput:
    info = activity.info()
    info.activity_id          # Unique activity ID
    info.activity_type        # Activity type name
    info.attempt              # Current attempt number (starts at 1)
    info.workflow_id          # Parent workflow ID
    info.workflow_run_id      # Parent workflow run ID
    info.task_token           # Token for async completion
    info.heartbeat_details    # Details from last heartbeat (on retry)
    info.scheduled_time       # When the activity was scheduled
    ...
```

## Workflow Definitions

### Basic Workflow

```python
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from my_app.activities import process_order
    from my_app.models import OrderInput, OrderResult

@workflow.defn
class OrderWorkflow:
    @workflow.run
    async def run(self, input: OrderInput) -> OrderResult:
        workflow.logger.info("Processing order %s", input.order_id)
        result = await workflow.execute_activity(
            process_order,
            input,
            start_to_close_timeout=timedelta(seconds=30),
        )
        return result
```

### Workflow Rules (Determinism)

Inside `@workflow.run` and all signal/query/update handlers, you must NOT:
- Use `datetime.now()`, `time.time()`, `random`, or `uuid4()` -- use `workflow.now()`, `workflow.random()`, `workflow.uuid4()` instead
- Perform I/O (network, file, database) -- use activities instead
- Use threading -- use `asyncio` primitives only
- Call non-deterministic library functions

You CAN use:
- `asyncio.sleep()` -- becomes a durable timer
- `asyncio.gather()` -- run activities in parallel
- `asyncio.Lock()` -- protect shared workflow state from interleaved handler execution
- `workflow.wait_condition()` -- wait for a boolean condition to become true

### Signals (send data into a running workflow)

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ApprovalInput:
    approver: str
    approved: bool

@workflow.defn
class ApprovalWorkflow:
    def __init__(self) -> None:
        self._approved: Optional[bool] = None
        self._approver: Optional[str] = None

    @workflow.run
    async def run(self, input: OrderInput) -> str:
        # Wait until we receive the approval signal
        await workflow.wait_condition(lambda: self._approved is not None)
        if self._approved:
            return f"Order {input.order_id} approved by {self._approver}"
        else:
            return f"Order {input.order_id} rejected by {self._approver}"

    @workflow.signal
    def approve(self, input: ApprovalInput) -> None:
        self._approved = input.approved
        self._approver = input.approver
```

### Queries (read workflow state without modifying it)

```python
@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._status = "pending"
        self._items_processed = 0

    @workflow.run
    async def run(self, input: OrderInput) -> OrderResult:
        self._status = "processing"
        # ... do work ...
        self._status = "completed"
        return result

    @workflow.query
    def get_status(self) -> str:
        return self._status

    @workflow.query
    def get_progress(self) -> int:
        return self._items_processed
```

Query handlers must NOT modify workflow state or call activities. They are read-only.

### Updates (send data and get a response, with optional validation)

```python
from temporalio.exceptions import ApplicationError

@workflow.defn
class ShoppingCartWorkflow:
    def __init__(self) -> None:
        self._items: dict[str, int] = {}
        self._checked_out = False

    @workflow.run
    async def run(self) -> dict:
        await workflow.wait_condition(lambda: self._checked_out)
        return self._items

    @workflow.update
    async def add_item(self, item_id: str, quantity: int) -> dict:
        self._items[item_id] = self._items.get(item_id, 0) + quantity
        return self._items

    @add_item.validator
    def validate_add_item(self, item_id: str, quantity: int) -> None:
        if self._checked_out:
            raise ApplicationError("Cannot add items after checkout")
        if quantity <= 0:
            raise ApplicationError("Quantity must be positive")

    @workflow.update
    async def checkout(self) -> dict:
        self._checked_out = True
        return self._items
```

Update validators run before the update handler and can reject the update by raising an exception. Validators must NOT modify workflow state.

### Wait Condition with Timeout

```python
@workflow.run
async def run(self, input: OrderInput) -> str:
    try:
        # Wait up to 24 hours for approval
        await workflow.wait_condition(
            lambda: self._approved is not None,
            timeout=timedelta(hours=24),
        )
        return "approved" if self._approved else "rejected"
    except asyncio.TimeoutError:
        return "timed_out"
```

### Wait for All Handlers to Finish

Before completing a workflow, ensure all signal and update handlers have finished:

```python
@workflow.run
async def run(self, input: MyInput) -> str:
    # ... main workflow logic ...

    # Wait for any in-progress signal/update handlers to complete
    await workflow.wait_condition(workflow.all_handlers_finished)
    return "done"
```

### Timers (Durable Sleep)

```python
@workflow.run
async def run(self, input: ReminderInput) -> None:
    # This sleep is durable -- if the worker crashes, the timer
    # continues on the server and fires when it expires
    await asyncio.sleep(3600)  # Wait 1 hour
    await workflow.execute_activity(
        send_reminder,
        input,
        start_to_close_timeout=timedelta(seconds=10),
    )
```

### Parallel Activities

```python
@workflow.run
async def run(self, users: list[str]) -> list[str]:
    # Run multiple activities concurrently using asyncio.gather
    results = await asyncio.gather(
        *[
            workflow.execute_activity(
                greet_user,
                user,
                start_to_close_timeout=timedelta(seconds=5),
            )
            for user in users
        ]
    )
    return list(results)
```

### Child Workflows

```python
@workflow.defn
class ParentWorkflow:
    @workflow.run
    async def run(self, input: ParentInput) -> str:
        # Execute and wait for child workflow result
        child_result = await workflow.execute_child_workflow(
            ChildWorkflow.run,
            ChildInput(data=input.data),
            id=f"child-{input.parent_id}",
        )
        return f"Parent got: {child_result}"

@workflow.defn
class ChildWorkflow:
    @workflow.run
    async def run(self, input: ChildInput) -> str:
        return await workflow.execute_activity(
            process_data,
            input,
            start_to_close_timeout=timedelta(seconds=30),
        )
```

Start a child workflow without waiting for its result:

```python
child_handle = await workflow.start_child_workflow(
    ChildWorkflow.run,
    ChildInput(data=input.data),
    id=f"child-{input.parent_id}",
)
# Can signal the child
await child_handle.signal(ChildWorkflow.some_signal, signal_data)
# Wait for result later
result = await child_handle
```

Parent close policy controls what happens to the child when the parent completes:

```python
from temporalio.workflow import ParentClosePolicy

child_result = await workflow.execute_child_workflow(
    ChildWorkflow.run,
    input,
    id="child-id",
    parent_close_policy=ParentClosePolicy.ABANDON,  # Child keeps running
    # Other options: TERMINATE (default), REQUEST_CANCEL
)
```

### Continue-As-New (for long-running / entity workflows)

Workflows accumulate event history. For workflows that run indefinitely or for very long periods, use continue-as-new to reset history while preserving logical state:

```python
@workflow.defn
class EntityWorkflow:
    @workflow.run
    async def run(self, state: EntityState) -> EntityResult:
        while not state.is_done:
            await workflow.wait_condition(
                lambda: state.has_pending_work or state.is_done,
                timeout=timedelta(minutes=10),
            )
            if state.has_pending_work:
                await self.process_work(state)

            # Check if Temporal suggests continuing as new
            if workflow.info().is_continue_as_new_suggested():
                # Finish any in-progress handlers first
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(state)

        return EntityResult(...)
```

`workflow.continue_as_new()` raises an internal exception that stops the current workflow execution and starts a new one with the same workflow ID, passing the provided arguments.

### Workflow Init (access input before run)

```python
@dataclass
class MyWorkflowInput:
    name: str

@workflow.defn
class MyWorkflow:
    @workflow.init
    def __init__(self, input: MyWorkflowInput) -> None:
        # Set up state before run() is called.
        # Same input is passed to both __init__ and run.
        self.greeting_prefix = f"Hello, {input.name}"

    @workflow.run
    async def run(self, input: MyWorkflowInput) -> str:
        return self.greeting_prefix
```

### Signaling External Workflows

```python
@workflow.defn
class WorkflowB:
    @workflow.run
    async def run(self) -> None:
        # Get a handle to another running workflow and signal it
        handle = workflow.get_external_workflow_handle_for(
            WorkflowA.run, "workflow-a-id"
        )
        await handle.signal(WorkflowA.some_signal, "signal data")
```

### Dynamic Signal and Query Handlers

```python
from typing import Sequence
from temporalio.common import RawValue

@workflow.defn
class FlexibleWorkflow:
    @workflow.signal(dynamic=True)
    async def dynamic_signal(self, name: str, args: Sequence[RawValue]) -> None:
        # Called for any signal that does not match a named handler
        payload = workflow.payload_converter().from_payload(args[0].payload, str)
        workflow.logger.info(f"Received dynamic signal '{name}': {payload}")

    @workflow.query(dynamic=True)
    def dynamic_query(self, name: str, args: Sequence[RawValue]) -> str:
        return f"Dynamic query '{name}' handled"
```

### Dynamic Workflow (catch-all)

```python
@workflow.defn(dynamic=True)
class DynamicWorkflow:
    @workflow.run
    async def run(self, args: Sequence[RawValue]) -> str:
        name = workflow.payload_converter().from_payload(args[0].payload, str)
        return f"Hello, {name}!"
```

### AsyncIO Lock for Handler Safety

When multiple signal or update handlers might modify the same state and include `await` points, use an `asyncio.Lock` to prevent interleaving:

```python
@workflow.defn
class SafeWorkflow:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.balance = 0

    @workflow.update
    async def transfer(self, amount: float) -> float:
        async with self.lock:
            # Check balance
            if self.balance < amount:
                raise ApplicationError("Insufficient funds")
            # This await yields control, but the lock prevents interleaving
            await workflow.execute_activity(
                record_transfer,
                amount,
                start_to_close_timeout=timedelta(seconds=10),
            )
            self.balance -= amount
            return self.balance
```

### Workflow Utility Functions

```python
# Inside a workflow:
workflow.info()                    # WorkflowInfo with id, run_id, task_queue, etc.
workflow.now()                     # Current time (deterministic)
workflow.random()                  # Random instance (deterministic, seeded)
workflow.uuid4()                   # Deterministic UUID generation
workflow.logger                    # Logger that includes workflow context
workflow.memo()                    # Access workflow memo
workflow.all_handlers_finished()   # True when all handlers are done
workflow.info().is_continue_as_new_suggested()  # Server recommends continue-as-new
workflow.info().get_current_history_length()     # Current event history size
```

## Worker Setup

### Basic Worker

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker

async def main():
    client = await Client.connect("localhost:7233")

    worker = Worker(
        client,
        task_queue="my-task-queue",
        workflows=[MyWorkflow],
        activities=[activity_a, activity_b],
        # Required for synchronous (non-async) activities:
        activity_executor=ThreadPoolExecutor(10),
    )
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### Worker as Context Manager

```python
async with Worker(
    client,
    task_queue="my-task-queue",
    workflows=[MyWorkflow],
    activities=[my_activity],
    activity_executor=ThreadPoolExecutor(10),
) as worker:
    # Worker is running, do other things...
    await some_other_task()
# Worker shuts down gracefully when exiting the context
```

### Worker with Activity Method Classes

```python
db_client = DatabaseClient(connection_string)
my_activities = MyActivities(db_client)

worker = Worker(
    client,
    task_queue="my-task-queue",
    workflows=[MyWorkflow],
    activities=[my_activities.fetch_record, my_activities.save_record],
)
```

### Key Worker Parameters

```python
Worker(
    client,
    task_queue="my-task-queue",
    workflows=[...],
    activities=[...],
    activity_executor=ThreadPoolExecutor(10),   # For sync activities
    max_concurrent_activities=100,               # Limit concurrent activities
    max_concurrent_workflow_tasks=100,           # Limit concurrent workflow tasks
    max_cached_workflows=100,                    # Workflow cache size
)
```

## Client Usage

### Connect to Temporal

```python
from temporalio.client import Client

# Local development
client = await Client.connect("localhost:7233")

# With namespace
client = await Client.connect("localhost:7233", namespace="my-namespace")

# Temporal Cloud with mTLS
client = await Client.connect(
    "my-namespace.a1b2c.tmprl.cloud:7233",
    namespace="my-namespace.a1b2c",
    tls=TLSConfig(
        client_cert=Path("client.pem").read_bytes(),
        client_private_key=Path("client.key").read_bytes(),
    ),
)
```

### Start a Workflow

```python
# Start and wait for result
result = await client.execute_workflow(
    MyWorkflow.run,
    MyInput(data="hello"),
    id="my-workflow-id",
    task_queue="my-task-queue",
)

# Start without waiting (returns handle)
handle = await client.start_workflow(
    MyWorkflow.run,
    MyInput(data="hello"),
    id="my-workflow-id",
    task_queue="my-task-queue",
)
# Get result later
result = await handle.result()
```

### Workflow Handle Operations

```python
# Get a handle to an existing workflow
handle = client.get_workflow_handle("my-workflow-id")

# Signal the workflow
await handle.signal(MyWorkflow.my_signal, SignalInput(data="value"))

# Query the workflow
status = await handle.query(MyWorkflow.get_status)

# Execute an update (send + wait for result)
update_result = await handle.execute_update(
    MyWorkflow.my_update, UpdateInput(data="value")
)

# Cancel the workflow
await handle.cancel()

# Terminate the workflow (immediate, no cleanup)
await handle.terminate("reason for termination")

# Describe the workflow (get execution info)
description = await handle.describe()
print(description.status)  # WorkflowExecutionStatus.RUNNING, COMPLETED, etc.

# Get the result (will raise WorkflowFailureError if workflow failed)
from temporalio.client import WorkflowFailureError
try:
    result = await handle.result()
except WorkflowFailureError as e:
    print(f"Workflow failed: {e}")
```

### Signal-With-Start

Start a workflow and send a signal atomically. If the workflow already exists, just sends the signal:

```python
handle = await client.start_workflow(
    MyWorkflow.run,
    MyInput(data="hello"),
    id="my-workflow-id",
    task_queue="my-task-queue",
    start_signal="my_signal",
    start_signal_args=[SignalInput(data="initial")],
)
```

### Start with Delay

```python
handle = await client.start_workflow(
    MyWorkflow.run,
    MyInput(data="hello"),
    id="my-workflow-id",
    task_queue="my-task-queue",
    start_delay=timedelta(hours=1),
)
```

### Workflow Retry Policy (from client)

```python
from temporalio.common import RetryPolicy

handle = await client.start_workflow(
    MyWorkflow.run,
    input_data,
    id="my-workflow-id",
    task_queue="my-task-queue",
    retry_policy=RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=10,
    ),
)
```

### Workflow Timeouts

```python
handle = await client.start_workflow(
    MyWorkflow.run,
    input_data,
    id="my-workflow-id",
    task_queue="my-task-queue",
    execution_timeout=timedelta(hours=24),    # Total time across all runs
    run_timeout=timedelta(hours=1),           # Single run (before continue-as-new)
    task_timeout=timedelta(seconds=30),       # Single workflow task
)
```

### List Workflows

```python
async for workflow_exec in client.list_workflows(
    "WorkflowType = 'MyWorkflow' AND ExecutionStatus = 'Running'"
):
    print(f"Workflow: {workflow_exec.id}, Status: {workflow_exec.status}")
```

### Schedules

```python
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleIntervalSpec,
    ScheduleState,
)

await client.create_schedule(
    "my-schedule-id",
    Schedule(
        action=ScheduleActionStartWorkflow(
            MyWorkflow.run,
            MyInput(data="scheduled"),
            id="scheduled-workflow",
            task_queue="my-task-queue",
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=5))]
        ),
        state=ScheduleState(note="Runs every 5 minutes"),
    ),
)

# Manage schedule
handle = client.get_schedule_handle("my-schedule-id")
await handle.pause(note="Pausing for maintenance")
await handle.trigger()  # Run immediately
await handle.delete()
desc = await handle.describe()
```

## Retry Policies

RetryPolicy controls how activities (and workflows) are retried on failure:

```python
from temporalio.common import RetryPolicy
from datetime import timedelta

retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=1),     # First retry delay
    backoff_coefficient=2.0,                    # Multiplier for subsequent delays
    maximum_interval=timedelta(seconds=60),     # Cap on retry delay
    maximum_attempts=5,                         # Max total attempts (0 = unlimited)
    non_retryable_error_types=["InvalidInput"], # Error types that skip retries
)
```

### Activity with Retry Policy

```python
result = await workflow.execute_activity(
    call_external_api,
    input_data,
    start_to_close_timeout=timedelta(seconds=30),
    retry_policy=RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=5,
    ),
)
```

### Activity Timeouts

```python
result = await workflow.execute_activity(
    my_activity,
    input_data,
    # Time from activity scheduled to completed (including retries + queue time)
    schedule_to_close_timeout=timedelta(minutes=5),
    # Time from activity picked up by worker to completed (single attempt)
    start_to_close_timeout=timedelta(seconds=30),
    # Time waiting in queue before a worker picks it up
    schedule_to_start_timeout=timedelta(seconds=60),
    # Max time between heartbeats before activity is considered failed
    heartbeat_timeout=timedelta(seconds=10),
)
```

You must set at least one of `schedule_to_close_timeout` or `start_to_close_timeout`.

### Custom Next Retry Delay

Override the retry delay from within an activity:

```python
from temporalio.exceptions import ApplicationError

@activity.defn
async def my_activity(input: MyInput) -> MyOutput:
    try:
        return await do_work(input)
    except Exception as e:
        attempt = activity.info().attempt
        raise ApplicationError(
            f"Failed on attempt {attempt}",
            next_retry_delay=timedelta(seconds=3 * attempt),
        ) from e
```

## Error Handling

### ApplicationError (business logic errors)

```python
from temporalio.exceptions import ApplicationError

# Retryable error (default)
raise ApplicationError("Temporary failure, will retry")

# Non-retryable error (will not be retried regardless of retry policy)
raise ApplicationError(
    "Invalid input: card number is malformed",
    type="InvalidInput",
    non_retryable=True,
)

# Error with custom type (can be matched by non_retryable_error_types)
raise ApplicationError(
    "Insufficient funds",
    type="InsufficientFunds",
)
```

### Catching Activity Errors in Workflows

```python
from temporalio.exceptions import ActivityError, ApplicationError

@workflow.run
async def run(self, input: OrderInput) -> OrderResult:
    try:
        result = await workflow.execute_activity(
            charge_payment,
            input,
            start_to_close_timeout=timedelta(seconds=30),
        )
    except ActivityError as e:
        # e.cause contains the original error (usually ApplicationError)
        workflow.logger.error(f"Payment failed: {e.cause}")
        # Handle the failure...
        raise ApplicationError(
            f"Order failed: {e.cause}",
            type="OrderFailed",
        )
```

### Catching Child Workflow Errors

```python
from temporalio.exceptions import ChildWorkflowError

try:
    result = await workflow.execute_child_workflow(
        ChildWorkflow.run,
        input_data,
        id="child-id",
    )
except ChildWorkflowError as e:
    workflow.logger.error(f"Child workflow failed: {e.cause}")
```

### Idempotency Keys

Use workflow and activity metadata to create idempotency keys for external calls:

```python
@activity.defn
async def charge_payment(input: PaymentInput) -> str:
    info = activity.info()
    idempotency_key = f"{info.workflow_run_id}-{info.activity_id}"
    return await payment_service.charge(
        amount=input.amount,
        idempotency_key=idempotency_key,
    )
```

## Cancellation

### Cancelling a Workflow from the Client

```python
handle = client.get_workflow_handle("my-workflow-id")
await handle.cancel()
```

### Handling Cancellation in Activities

Activities must heartbeat to receive cancellation. When cancelled, `asyncio.CancelledError` (async) or `temporalio.exceptions.CancelledError` (sync) is raised:

```python
@activity.defn
async def cancellable_activity(input: MyInput) -> None:
    try:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)
            await do_some_work()
    except asyncio.CancelledError:
        # Perform cleanup
        await cleanup()
        raise  # Must re-raise for proper cancellation

@activity.defn
def sync_cancellable_activity(input: MyInput) -> None:
    try:
        while True:
            activity.heartbeat()
            time.sleep(1)
    except CancelledError:
        cleanup()
        raise  # Must re-raise
```

### Handling Cancellation in Workflows with Cleanup

```python
@workflow.defn
class WorkflowWithCleanup:
    @workflow.run
    async def run(self) -> None:
        try:
            await workflow.execute_activity(
                long_running_activity,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=10),
            )
        finally:
            # Cleanup runs even on cancellation
            await workflow.execute_activity(
                cleanup_activity,
                start_to_close_timeout=timedelta(seconds=30),
            )
```

### Cancelling an Activity from a Workflow

```python
@workflow.run
async def run(self) -> None:
    activity_handle = workflow.start_activity(
        long_running_activity,
        start_to_close_timeout=timedelta(hours=1),
        heartbeat_timeout=timedelta(seconds=10),
    )
    # Wait, then cancel
    await asyncio.sleep(60)
    activity_handle.cancel()
```

## Versioning (Patching)

Use patching to safely change workflow logic while existing executions are still running:

### Step 1: Add a patch

```python
@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self) -> None:
        if workflow.patched("my-change-id"):
            # New code path
            result = await workflow.execute_activity(
                new_activity,
                schedule_to_close_timeout=timedelta(minutes=5),
            )
        else:
            # Old code path (for in-flight workflows)
            result = await workflow.execute_activity(
                old_activity,
                schedule_to_close_timeout=timedelta(minutes=5),
            )
```

### Step 2: Deprecate the patch (after all old executions complete)

```python
@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self) -> None:
        workflow.deprecate_patch("my-change-id")
        result = await workflow.execute_activity(
            new_activity,
            schedule_to_close_timeout=timedelta(minutes=5),
        )
```

### Step 3: Remove the deprecation (after another full cycle)

```python
@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self) -> None:
        result = await workflow.execute_activity(
            new_activity,
            schedule_to_close_timeout=timedelta(minutes=5),
        )
```

## Testing

### Test Setup with pytest (conftest.py)

```python
import pytest
import pytest_asyncio
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

@pytest_asyncio.fixture(scope="session")
async def env():
    # start_local() starts a real lightweight Temporal server
    # start_time_skipping() uses a test server that auto-advances time
    env = await WorkflowEnvironment.start_local()
    yield env
    await env.shutdown()

@pytest_asyncio.fixture
async def client(env: WorkflowEnvironment) -> Client:
    return env.client
```

### Test a Workflow End-to-End

```python
import uuid
from concurrent.futures import ThreadPoolExecutor
from temporalio.worker import Worker

async def test_order_workflow(client: Client):
    task_queue = str(uuid.uuid4())

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[OrderWorkflow],
        activities=[process_order, send_confirmation],
        activity_executor=ThreadPoolExecutor(5),
    ):
        result = await client.execute_workflow(
            OrderWorkflow.run,
            OrderInput(order_id="123", customer_name="Alice", amount=99.99),
            id=str(uuid.uuid4()),
            task_queue=task_queue,
        )
        assert result.status == "completed"
        assert result.confirmation_number is not None
```

### Test with Mocked Activities

Define a mock activity with the same name as the real one using `@activity.defn(name="...")`:

```python
from temporalio import activity

@activity.defn(name="process_order")
async def mock_process_order(input: OrderInput) -> OrderResult:
    return OrderResult(
        order_id=input.order_id,
        status="completed",
        confirmation_number="MOCK-123",
    )

async def test_workflow_with_mock(client: Client):
    task_queue = str(uuid.uuid4())
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[OrderWorkflow],
        activities=[mock_process_order],  # Use mock instead of real activity
    ):
        result = await client.execute_workflow(
            OrderWorkflow.run,
            OrderInput(order_id="123", customer_name="Alice", amount=99.99),
            id=str(uuid.uuid4()),
            task_queue=task_queue,
        )
        assert result.confirmation_number == "MOCK-123"
```

### Test Signals

```python
from temporalio.client import WorkflowExecutionStatus

async def test_signal_workflow(client: Client):
    task_queue = str(uuid.uuid4())
    async with Worker(client, task_queue=task_queue, workflows=[ApprovalWorkflow]):
        handle = await client.start_workflow(
            ApprovalWorkflow.run,
            OrderInput(order_id="123", customer_name="Alice", amount=99.99),
            id=str(uuid.uuid4()),
            task_queue=task_queue,
        )

        # Verify running
        assert WorkflowExecutionStatus.RUNNING == (await handle.describe()).status

        # Send signal
        await handle.signal(
            ApprovalWorkflow.approve,
            ApprovalInput(approver="Bob", approved=True),
        )

        # Wait for result
        result = await handle.result()
        assert "approved" in result
```

### Test Activities in Isolation

```python
from temporalio.testing import ActivityEnvironment

async def test_activity_with_heartbeat():
    env = ActivityEnvironment()

    # Capture heartbeats
    heartbeats = []
    env.on_heartbeat = lambda *args: heartbeats.append(args[0])

    result = await env.run(process_large_dataset, DatasetInput(file_path="test.csv"))
    assert result.total_rows > 0
    assert len(heartbeats) > 0
```

### Test with Time Skipping

For workflows that use timers (asyncio.sleep), use the time-skipping environment:

```python
@pytest_asyncio.fixture(scope="session")
async def env():
    env = await WorkflowEnvironment.start_time_skipping()
    yield env
    await env.shutdown()

async def test_reminder_workflow(client: Client):
    task_queue = str(uuid.uuid4())
    async with Worker(client, task_queue=task_queue, workflows=[ReminderWorkflow]):
        # This workflow sleeps for 24 hours, but time-skipping makes it instant
        result = await client.execute_workflow(
            ReminderWorkflow.run,
            ReminderInput(message="test"),
            id=str(uuid.uuid4()),
            task_queue=task_queue,
        )
        assert result == "reminder_sent"
```

### Replay Testing (detect non-deterministic changes)

```python
from temporalio.worker import Replayer
from temporalio.workflow import WorkflowHistory

async def test_replay_from_history():
    replayer = Replayer(workflows=[MyWorkflow])
    # Replay from a JSON history file
    with open("workflow_history.json") as f:
        await replayer.replay_workflow(
            WorkflowHistory.from_json(f.read())
        )

async def test_replay_from_server(client: Client):
    workflows = client.list_workflows("WorkflowType = 'MyWorkflow'")
    histories = workflows.map_histories()
    replayer = Replayer(workflows=[MyWorkflow])
    await replayer.replay_workflows(histories, raise_on_replay_failure=False)
```

## Key Patterns

### Saga / Compensation Pattern

Execute a sequence of activities, rolling back completed steps if any step fails:

```python
from dataclasses import dataclass, field
from typing import Any, Callable, List
from temporalio.exceptions import ActivityError, ApplicationError

@dataclass
class Compensation:
    activity: Any  # Activity function reference
    input: Any     # Input to pass to compensation activity

@workflow.defn
class OrderSagaWorkflow:
    @workflow.run
    async def run(self, input: OrderInput) -> OrderResult:
        compensations: List[Compensation] = []

        try:
            # Step 1: Reserve inventory
            await workflow.execute_activity(
                reserve_inventory,
                input,
                start_to_close_timeout=timedelta(seconds=30),
            )
            compensations.append(Compensation(
                activity=release_inventory,
                input=input,
            ))

            # Step 2: Charge payment
            payment = await workflow.execute_activity(
                charge_payment,
                PaymentInput(order_id=input.order_id, amount=input.amount),
                start_to_close_timeout=timedelta(seconds=30),
            )
            compensations.append(Compensation(
                activity=refund_payment,
                input=PaymentInput(order_id=input.order_id, amount=input.amount),
            ))

            # Step 3: Create shipment
            shipment = await workflow.execute_activity(
                create_shipment,
                ShipmentInput(order_id=input.order_id, address=input.address),
                start_to_close_timeout=timedelta(seconds=30),
            )

            return OrderResult(
                order_id=input.order_id,
                status="completed",
                confirmation_number=shipment.tracking_id,
            )

        except ActivityError as e:
            workflow.logger.error(f"Saga step failed: {e.cause}, compensating...")
            # Run compensations in reverse order
            for compensation in reversed(compensations):
                try:
                    await workflow.execute_activity(
                        compensation.activity,
                        compensation.input,
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                except ActivityError as comp_err:
                    workflow.logger.error(
                        f"Compensation failed: {comp_err.cause}"
                    )
            raise ApplicationError(
                f"Order saga failed: {e.cause}",
                type="SagaFailed",
            )
```

### Long-Running Entity Workflow

A workflow that runs indefinitely, processing signals and updates, and periodically continues-as-new to avoid history growth:

```python
@dataclass
class EntityState:
    items: dict = field(default_factory=dict)
    is_shutdown: bool = False

@workflow.defn
class EntityWorkflow:
    @workflow.init
    def __init__(self, state: EntityState) -> None:
        self.state = state
        self.lock = asyncio.Lock()

    @workflow.run
    async def run(self, state: EntityState) -> EntityState:
        while not self.state.is_shutdown:
            try:
                await workflow.wait_condition(
                    lambda: self.state.is_shutdown or self.should_continue_as_new(),
                    timeout=timedelta(minutes=10),
                )
            except asyncio.TimeoutError:
                # Periodic maintenance
                await self.perform_maintenance()

            if self.should_continue_as_new():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(self.state)

        await workflow.wait_condition(workflow.all_handlers_finished)
        return self.state

    @workflow.signal
    def shutdown(self) -> None:
        self.state.is_shutdown = True

    @workflow.update
    async def add_item(self, key: str, value: str) -> dict:
        async with self.lock:
            self.state.items[key] = value
            await workflow.execute_activity(
                persist_item,
                PersistInput(key=key, value=value),
                start_to_close_timeout=timedelta(seconds=10),
            )
            return self.state.items

    @workflow.query
    def get_items(self) -> dict:
        return self.state.items

    def should_continue_as_new(self) -> bool:
        return workflow.info().is_continue_as_new_suggested()

    async def perform_maintenance(self) -> None:
        async with self.lock:
            await workflow.execute_activity(
                run_maintenance,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
```

### Polling Pattern (wait for external condition)

```python
@workflow.defn
class PollingWorkflow:
    @workflow.run
    async def run(self, input: PollInput) -> PollResult:
        for attempt in range(input.max_attempts):
            result = await workflow.execute_activity(
                check_status,
                input,
                start_to_close_timeout=timedelta(seconds=10),
            )
            if result.is_ready:
                return result
            # Durable sleep between polls
            await asyncio.sleep(input.poll_interval_seconds)

        raise ApplicationError("Polling timed out", type="PollTimeout")
```

### Fan-Out / Fan-In

```python
@workflow.run
async def run(self, items: list[ItemInput]) -> list[ItemResult]:
    # Fan out: start all activities concurrently
    results = await asyncio.gather(
        *[
            workflow.execute_activity(
                process_item,
                item,
                start_to_close_timeout=timedelta(seconds=30),
            )
            for item in items
        ]
    )
    # Fan in: aggregate results
    return list(results)
```

### Approval / Human-in-the-Loop

```python
@workflow.defn
class ApprovalWorkflow:
    def __init__(self) -> None:
        self._decision: Optional[bool] = None

    @workflow.run
    async def run(self, input: ApprovalInput) -> str:
        # Notify reviewer
        await workflow.execute_activity(
            send_approval_request,
            input,
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Wait for human decision with timeout
        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(hours=72),
            )
        except asyncio.TimeoutError:
            return "timed_out"

        if self._decision:
            await workflow.execute_activity(
                execute_approved_action,
                input,
                start_to_close_timeout=timedelta(seconds=30),
            )
            return "approved"
        else:
            return "rejected"

    @workflow.signal
    def decide(self, approved: bool) -> None:
        self._decision = approved
```

## Complete Working Example

A full single-file example showing all pieces together:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker


# --- Models ---

@dataclass
class GreetingInput:
    name: str
    greeting: str = "Hello"


@dataclass
class GreetingResult:
    message: str
    attempts: int


# --- Activities ---

@activity.defn
def compose_greeting(input: GreetingInput) -> GreetingResult:
    activity.logger.info("Composing greeting for %s", input.name)
    return GreetingResult(
        message=f"{input.greeting}, {input.name}!",
        attempts=activity.info().attempt,
    )


# --- Workflows ---

@workflow.defn
class GreetingWorkflow:
    def __init__(self) -> None:
        self._greeting_count = 0
        self._last_greeting = ""

    @workflow.run
    async def run(self, input: GreetingInput) -> str:
        result = await workflow.execute_activity(
            compose_greeting,
            input,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._greeting_count += 1
        self._last_greeting = result.message
        return result.message

    @workflow.query
    def get_count(self) -> int:
        return self._greeting_count

    @workflow.query
    def get_last_greeting(self) -> str:
        return self._last_greeting


# --- Main ---

async def main():
    client = await Client.connect("localhost:7233")

    async with Worker(
        client,
        task_queue="greeting-task-queue",
        workflows=[GreetingWorkflow],
        activities=[compose_greeting],
        activity_executor=ThreadPoolExecutor(5),
    ):
        result = await client.execute_workflow(
            GreetingWorkflow.run,
            GreetingInput(name="World"),
            id="greeting-workflow-1",
            task_queue="greeting-task-queue",
        )
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
```
