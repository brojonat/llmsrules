---
name: temporal-go
description: Build Temporal workflow applications in Go. Use when creating or modifying Temporal workflows, activities, workers, clients, signals, queries, updates, retry policies, saga patterns, or writing Temporal tests.
---

# Temporal Go SDK

Build durable, fault-tolerant distributed applications using the Temporal Go SDK (`go.temporal.io/sdk`). Temporal provides workflow orchestration with automatic retries, state persistence, and exactly-once execution semantics.

## Core Principles

- **Deterministic Workflows**: Workflow code must be deterministic. Never use `time.Now()`, `rand`, `map` range, goroutines, or I/O directly in Workflows.
- **Activities for Side Effects**: All non-deterministic operations (HTTP calls, DB queries, file I/O) go in Activities.
- **Struct Parameters**: Use single struct parameters and return values for forward compatibility.
- **Idempotent Activities**: Activities may be retried; design them to be safely re-executable.
- **Explicit Error Handling**: Use Temporal's typed errors (`ApplicationError`, `TimeoutError`, `CanceledError`) for control flow.

## Project Structure

```
.
├── cmd/
│   ├── worker/           # Worker process entry point
│   └── starter/          # Workflow starter (client) entry point
├── workflows/            # Workflow definitions
│   ├── order.go
│   └── order_test.go
├── activities/           # Activity definitions
│   ├── payment.go
│   └── payment_test.go
├── shared/               # Shared types (params, results, constants)
│   └── types.go
├── go.mod
└── go.sum
```

## Imports

```go
import (
    // Client - for connecting to Temporal and starting workflows
    "go.temporal.io/sdk/client"

    // Workflow - for writing workflow definitions
    "go.temporal.io/sdk/workflow"

    // Activity - for writing activity definitions
    "go.temporal.io/sdk/activity"

    // Worker - for creating and running workers
    "go.temporal.io/sdk/worker"

    // Temporal - for error types and retry policies
    "go.temporal.io/sdk/temporal"

    // Testing - for test environments
    "go.temporal.io/sdk/testsuite"

    // Logging
    "go.temporal.io/sdk/log"
)
```

## Workflow Definitions

### Basic Workflow

A Workflow Definition is an exportable function. The first parameter must be `workflow.Context`. Return `error` or `(result, error)`. Use struct params for forward compatibility.

```go
package workflows

import (
    "time"
    "go.temporal.io/sdk/workflow"
)

type OrderInput struct {
    OrderID    string
    CustomerID string
    Items      []string
    Amount     float64
}

type OrderResult struct {
    OrderID       string
    PaymentID     string
    TrackingCode  string
    CompletedAt   string
}

func ProcessOrder(ctx workflow.Context, input OrderInput) (*OrderResult, error) {
    logger := workflow.GetLogger(ctx)
    logger.Info("ProcessOrder started", "orderID", input.OrderID)

    // Set activity options (StartToCloseTimeout OR ScheduleToCloseTimeout required)
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: 30 * time.Second,
        RetryPolicy: &temporal.RetryPolicy{
            InitialInterval:    time.Second,
            BackoffCoefficient: 2.0,
            MaximumInterval:    time.Minute,
            MaximumAttempts:    5,
        },
    }
    ctx = workflow.WithActivityOptions(ctx, ao)

    // Use nil struct pointer to call struct-method Activities
    var a *Activities

    var paymentResult PaymentResult
    err := workflow.ExecuteActivity(ctx, a.ChargePayment, input).Get(ctx, &paymentResult)
    if err != nil {
        return nil, err
    }

    var shippingResult ShippingResult
    err = workflow.ExecuteActivity(ctx, a.ShipOrder, input).Get(ctx, &shippingResult)
    if err != nil {
        return nil, err
    }

    return &OrderResult{
        OrderID:      input.OrderID,
        PaymentID:    paymentResult.PaymentID,
        TrackingCode: shippingResult.TrackingCode,
        CompletedAt:  workflow.Now(ctx).Format(time.RFC3339),
    }, nil
}
```

### Determinism Rules

Workflow code MUST be deterministic. Use Temporal SDK replacements for non-deterministic Go constructs:

| Go Construct | Temporal Replacement | Package |
|---|---|---|
| `time.Now()` | `workflow.Now(ctx)` | `workflow` |
| `time.Sleep()` | `workflow.Sleep(ctx, d)` | `workflow` |
| `go func()` | `workflow.Go(ctx, func(ctx workflow.Context) {...})` | `workflow` |
| `chan` | `workflow.Channel` / `workflow.NewChannel(ctx)` | `workflow` |
| `select` | `workflow.Selector` / `workflow.NewSelector(ctx)` | `workflow` |
| `context.Context` | `workflow.Context` | `workflow` |
| `rand.Intn()` | `workflow.SideEffect(ctx, func(...) interface{})` | `workflow` |
| `log.Println()` | `workflow.GetLogger(ctx).Info(...)` | `workflow` |
| `range` over `map` | `workflow.DeterministicKeys(m)` then iterate | `workflow` |

### Logging (replay-safe)

Always use `workflow.GetLogger(ctx)` -- it suppresses duplicate logs during replay:

```go
logger := workflow.GetLogger(ctx)
logger.Info("Processing started", "orderID", orderID)
logger.Error("Activity failed", "Error", err)
```

### Side Effects

Capture non-deterministic values (random numbers, UUIDs) so they are recorded in history and replayed consistently:

```go
encodedRandom := workflow.SideEffect(ctx, func(ctx workflow.Context) interface{} {
    return rand.Intn(100)
})
var randomValue int
encodedRandom.Get(&randomValue)
```

### Selectors (replacing `select`)

Use `workflow.Selector` to wait on multiple Futures and Channels. The selector picks the first ready callback.

```go
func SampleTimerWorkflow(ctx workflow.Context, timeout time.Duration) error {
    ao := workflow.ActivityOptions{StartToCloseTimeout: 10 * time.Second}
    ctx = workflow.WithActivityOptions(ctx, ao)

    childCtx, cancelHandler := workflow.WithCancel(ctx)
    selector := workflow.NewSelector(ctx)

    var processingDone bool

    // Add a Future (activity result)
    f := workflow.ExecuteActivity(ctx, OrderProcessingActivity)
    selector.AddFuture(f, func(f workflow.Future) {
        processingDone = true
        cancelHandler() // cancel the timer
    })

    // Add a timer Future
    timerFuture := workflow.NewTimer(childCtx, timeout)
    selector.AddFuture(timerFuture, func(f workflow.Future) {
        if !processingDone {
            _ = workflow.ExecuteActivity(ctx, SendNotificationActivity).Get(ctx, nil)
        }
    })

    // Wait for the first to complete
    selector.Select(ctx)

    // If timer fired first, still wait for processing to finish
    if !processingDone {
        selector.Select(ctx)
    }

    return nil
}
```

### Timers

```go
// Simple sleep
workflow.Sleep(ctx, 5*time.Minute)

// Cancellable timer via NewTimer
timerCtx, timerCancel := workflow.WithCancel(ctx)
timer := workflow.NewTimer(timerCtx, 30*time.Minute)

// Cancel the timer when no longer needed
timerCancel()
```

### Goroutines (workflow.Go)

Never use native `go` -- use `workflow.Go()` for deterministic coroutines:

```go
func SampleGoroutineWorkflow(ctx workflow.Context, parallelism int) ([]string, error) {
    ao := workflow.ActivityOptions{StartToCloseTimeout: 10 * time.Second}
    ctx = workflow.WithActivityOptions(ctx, ao)

    var results []string
    var err error

    for i := 0; i < parallelism; i++ {
        input := fmt.Sprint(i) // capture outside lambda
        workflow.Go(ctx, func(gCtx workflow.Context) {
            // IMPORTANT: use gCtx (the goroutine context), not ctx
            var result string
            err = workflow.ExecuteActivity(gCtx, ProcessItem, input).Get(gCtx, &result)
            if err != nil {
                return
            }
            results = append(results, result)
        })
    }

    // Wait for all goroutines to complete
    _ = workflow.Await(ctx, func() bool {
        return err != nil || len(results) == parallelism
    })
    return results, err
}
```

### Await and AwaitWithTimeout

Block a Workflow until a condition becomes true, without polling:

```go
// Block indefinitely until condition is met
err := workflow.Await(ctx, func() bool {
    return isApproved
})

// Block with a timeout
ok, err := workflow.AwaitWithTimeout(ctx, 30*time.Second, func() bool {
    return isApproved
})
if err != nil {
    return err // canceled
}
if !ok {
    return temporal.NewApplicationError("approval timed out", "timeout")
}
```

### Child Workflows

Execute a Workflow from within another Workflow:

```go
func ParentWorkflow(ctx workflow.Context) (string, error) {
    cwo := workflow.ChildWorkflowOptions{
        WorkflowID: "child-workflow-id",
        // Optional: TaskQueue, RetryPolicy, etc.
    }
    ctx = workflow.WithChildOptions(ctx, cwo)

    var result string
    err := workflow.ExecuteChildWorkflow(ctx, ChildWorkflow, "input-data").Get(ctx, &result)
    if err != nil {
        return "", err
    }
    return result, nil
}

func ChildWorkflow(ctx workflow.Context, input string) (string, error) {
    logger := workflow.GetLogger(ctx)
    logger.Info("Child workflow started", "input", input)
    return "processed: " + input, nil
}
```

### Continue-As-New

For long-running Workflows, use Continue-As-New to keep Event History from growing too large. This closes the current Workflow Execution and starts a fresh one with the same Workflow ID:

```go
func LongRunningWorkflow(ctx workflow.Context, state WorkflowState) error {
    // Check if Temporal suggests continuing as new
    if workflow.GetInfo(ctx).GetContinueAsNewSuggested() {
        return workflow.NewContinueAsNewError(ctx, LongRunningWorkflow, state)
    }

    // ... do work, update state ...

    // Explicitly continue as new after N iterations
    state.Iteration++
    if state.Iteration >= 1000 {
        return workflow.NewContinueAsNewError(ctx, LongRunningWorkflow, state)
    }

    return nil
}
```

When using Update or Signal handlers, wait for them to finish before continuing as new:

```go
err := workflow.Await(ctx, func() bool {
    return workflow.AllHandlersFinished(ctx)
})
if err != nil {
    return err
}
return workflow.NewContinueAsNewError(ctx, MyWorkflow, updatedState)
```

## Signals

Signals are asynchronous messages sent to a running Workflow to change its state.

### Handle Signals in a Workflow

```go
const ApproveSignal = "approve"

type ApproveInput struct {
    ApproverName string
}

func ApprovalWorkflow(ctx workflow.Context, orderID string) error {
    logger := workflow.GetLogger(ctx)

    // Get the signal channel
    signalChan := workflow.GetSignalChannel(ctx, ApproveSignal)

    // Block until signal is received
    var approval ApproveInput
    signalChan.Receive(ctx, &approval)
    logger.Info("Received approval", "approver", approval.ApproverName)

    // Continue workflow execution after signal...
    return nil
}
```

### Listen for Signals in a Background Goroutine

```go
func OrderWorkflow(ctx workflow.Context) error {
    var lastSignalData string

    // Listen for signals in a separate goroutine
    workflow.Go(ctx, func(gCtx workflow.Context) {
        signalChan := workflow.GetSignalChannel(gCtx, "my-signal")
        for {
            selector := workflow.NewSelector(gCtx)
            selector.AddReceive(signalChan, func(c workflow.ReceiveChannel, more bool) {
                c.Receive(gCtx, &lastSignalData)
            })
            selector.Select(gCtx)
        }
    })

    // Main workflow logic continues...
    // lastSignalData is updated whenever a signal arrives
    return nil
}
```

### Drain Signals Before Continue-As-New

Always drain buffered signals before completing or continuing as new:

```go
signalChan := workflow.GetSignalChannel(ctx, "my-signal")
for {
    var data string
    ok := signalChan.ReceiveAsync(&data)
    if !ok {
        break
    }
    // process data
}
```

## Queries

Queries are synchronous, read-only operations that inspect Workflow state. Query handlers must NOT mutate state.

### Set a Query Handler

```go
func QueryableWorkflow(ctx workflow.Context) error {
    currentState := "initialized"

    // Register a query handler
    err := workflow.SetQueryHandler(ctx, "get-state", func() (string, error) {
        return currentState, nil
    })
    if err != nil {
        return err
    }

    // Query handlers with input parameters
    err = workflow.SetQueryHandler(ctx, "get-item", func(itemID string) (*Item, error) {
        item, ok := items[itemID]
        if !ok {
            return nil, fmt.Errorf("item %s not found", itemID)
        }
        return item, nil
    })
    if err != nil {
        return err
    }

    // Workflow logic that updates currentState...
    currentState = "processing"
    workflow.Sleep(ctx, time.Minute)
    currentState = "done"
    return nil
}
```

## Updates

Updates are synchronous, trackable requests that can mutate Workflow state and return results. They support validators for rejecting invalid requests before they are written to history.

### Set an Update Handler

```go
const FetchAndAdd = "fetch_and_add"
const Done = "done"

func CounterWorkflow(ctx workflow.Context) (int, error) {
    counter := 0

    // Update handler with validator
    err := workflow.SetUpdateHandlerWithOptions(
        ctx,
        FetchAndAdd,
        func(ctx workflow.Context, addend int) (int, error) {
            previous := counter
            counter += addend
            return previous, nil
        },
        workflow.UpdateHandlerOptions{
            Validator: func(ctx workflow.Context, addend int) error {
                if addend < 0 {
                    return fmt.Errorf("addend must be non-negative (%d)", addend)
                }
                return nil
            },
        },
    )
    if err != nil {
        return 0, err
    }

    // Wait for a "done" signal to finish
    _ = workflow.GetSignalChannel(ctx, Done).Receive(ctx, nil)
    return counter, ctx.Err()
}
```

### Update Handlers with Activities and Mutexes

For safe concurrent access, use `workflow.Mutex`:

```go
type Manager struct {
    state    map[string]string
    nodeLock workflow.Mutex
}

func (m *Manager) AssignNode(ctx workflow.Context, input AssignInput) (AssignResult, error) {
    // Wait until ready
    err := workflow.Await(ctx, func() bool { return m.isStarted })
    if err != nil {
        return AssignResult{}, err
    }

    // Acquire mutex for safe concurrent access
    err = m.nodeLock.Lock(ctx)
    if err != nil {
        return AssignResult{}, err
    }
    defer m.nodeLock.Unlock()

    // Execute activity while holding lock
    actCtx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
        ScheduleToCloseTimeout: 10 * time.Second,
    })
    err = workflow.ExecuteActivity(actCtx, DoAssignment, input).Get(actCtx, nil)
    if err != nil {
        return AssignResult{}, err
    }

    m.state[input.NodeID] = input.JobName
    return AssignResult{NodeID: input.NodeID}, nil
}
```

## Activity Definitions

### Basic Activity

Activities are normal Go functions. The first parameter should be `context.Context`. They can perform any operation (I/O, HTTP calls, DB queries).

```go
package activities

import (
    "context"
    "go.temporal.io/sdk/activity"
)

// Simple function activity
func SendEmail(ctx context.Context, recipient, subject, body string) error {
    logger := activity.GetLogger(ctx)
    logger.Info("Sending email", "to", recipient)
    // ... actual email sending logic ...
    return nil
}
```

### Struct-Based Activities (recommended for dependencies)

Use struct methods when Activities need shared dependencies (DB pools, HTTP clients, configs). This is the recommended pattern.

```go
type Activities struct {
    DBPool    *pgxpool.Pool
    APIClient *http.Client
    Config    *AppConfig
}

type PaymentInput struct {
    OrderID  string
    Amount   float64
    Currency string
}

type PaymentResult struct {
    PaymentID string
    Status    string
}

func (a *Activities) ChargePayment(ctx context.Context, input PaymentInput) (*PaymentResult, error) {
    logger := activity.GetLogger(ctx)
    logger.Info("Charging payment", "orderID", input.OrderID, "amount", input.Amount)

    // Use shared dependencies
    result, err := a.APIClient.Post(/* ... */)
    if err != nil {
        return nil, err
    }

    return &PaymentResult{
        PaymentID: result.ID,
        Status:    "charged",
    }, nil
}

func (a *Activities) RefundPayment(ctx context.Context, input PaymentInput) error {
    // Compensation activity for saga pattern
    logger := activity.GetLogger(ctx)
    logger.Info("Refunding payment", "orderID", input.OrderID)
    // ... refund logic ...
    return nil
}
```

When calling struct-method activities from a Workflow, use a nil struct pointer:

```go
// In workflow code:
var a *Activities  // nil pointer is fine -- used only for method resolution
err := workflow.ExecuteActivity(ctx, a.ChargePayment, input).Get(ctx, &result)
```

### Activity Heartbeating

Long-running Activities should heartbeat to report progress. If the Activity fails and retries, it can resume from the last heartbeated progress.

```go
func BatchProcessingActivity(ctx context.Context, startIdx, endIdx int) error {
    logger := activity.GetLogger(ctx)

    // Resume from last heartbeat on retry
    i := startIdx
    if activity.HasHeartbeatDetails(ctx) {
        var lastCompleted int
        if err := activity.GetHeartbeatDetails(ctx, &lastCompleted); err == nil {
            i = lastCompleted + 1
            logger.Info("Resuming from heartbeat", "index", i)
        }
    }

    for ; i <= endIdx; i++ {
        // Do work for item i...
        logger.Info("Processing item", "index", i)

        // Record progress -- also delivers cancellation signals
        activity.RecordHeartbeat(ctx, i)

        // Check for cancellation
        select {
        case <-ctx.Done():
            return ctx.Err()
        default:
        }
    }

    return nil
}
```

Set `HeartbeatTimeout` in the Workflow's `ActivityOptions`:

```go
ao := workflow.ActivityOptions{
    StartToCloseTimeout: 24 * time.Hour,
    HeartbeatTimeout:    30 * time.Second,  // Must heartbeat at least every 30s
}
```

### Activity Errors

```go
import "go.temporal.io/sdk/temporal"

// Retryable error (default) -- will be retried per RetryPolicy
return temporal.NewApplicationError("temporary failure", "TempError", details)

// Non-retryable error -- will NOT be retried regardless of RetryPolicy
return temporal.NewNonRetryableApplicationError("bad input", "ValidationError", nil, details)

// Standard Go errors are converted to retryable ApplicationError automatically
return fmt.Errorf("something went wrong: %w", err)
```

## Worker Setup

A Worker polls a Task Queue for Workflow Tasks and Activity Tasks.

```go
package main

import (
    "log"

    "go.temporal.io/sdk/client"
    "go.temporal.io/sdk/worker"

    "myapp/activities"
    "myapp/workflows"
)

func main() {
    // Create a Temporal client (heavyweight -- create once per process)
    c, err := client.Dial(client.Options{
        HostPort:  "localhost:7233",       // default
        Namespace: "default",              // default
    })
    if err != nil {
        log.Fatalln("Unable to create client", err)
    }
    defer c.Close()

    // Create a Worker that listens on a specific Task Queue
    w := worker.New(c, "my-task-queue", worker.Options{
        // Optional: tune worker concurrency
        // MaxConcurrentActivityExecutionSize:     defaults to 1000
        // MaxConcurrentWorkflowTaskExecutionSize: defaults to 1000
    })

    // Register Workflow functions
    w.RegisterWorkflow(workflows.ProcessOrder)
    w.RegisterWorkflow(workflows.ApprovalWorkflow)

    // Register Activity struct (registers all exported methods)
    w.RegisterActivity(&activities.Activities{
        DBPool:    dbPool,
        APIClient: httpClient,
        Config:    config,
    })

    // Register standalone Activity functions
    w.RegisterActivity(activities.SendEmail)

    // Run the Worker (blocks until interrupt signal)
    err = w.Run(worker.InterruptCh())
    if err != nil {
        log.Fatalln("Unable to start worker", err)
    }
}
```

### Custom Registration Names

```go
// Custom Workflow type name
w.RegisterWorkflowWithOptions(workflows.ProcessOrder, workflow.RegisterOptions{
    Name: "OrderProcessing",
})

// Custom Activity type name
w.RegisterActivityWithOptions(activities.SendEmail, activity.RegisterOptions{
    Name: "EmailSender",
})
```

## Client Usage

### Starting a Workflow

```go
package main

import (
    "context"
    "log"

    "go.temporal.io/sdk/client"
    "myapp/workflows"
)

func main() {
    c, err := client.Dial(client.Options{
        HostPort: client.DefaultHostPort,
    })
    if err != nil {
        log.Fatalln("Unable to create client", err)
    }
    defer c.Close()

    options := client.StartWorkflowOptions{
        ID:        "order-12345",          // Workflow ID (should be meaningful)
        TaskQueue: "my-task-queue",        // Must match Worker's task queue
        // Optional:
        // WorkflowExecutionTimeout: 24 * time.Hour,
        // RetryPolicy: &temporal.RetryPolicy{...},
    }

    input := workflows.OrderInput{
        OrderID:    "12345",
        CustomerID: "cust-789",
        Items:      []string{"item-a", "item-b"},
        Amount:     99.99,
    }

    we, err := c.ExecuteWorkflow(context.Background(), options, workflows.ProcessOrder, input)
    if err != nil {
        log.Fatalln("Unable to execute workflow", err)
    }

    log.Println("Started workflow", "WorkflowID", we.GetID(), "RunID", we.GetRunID())

    // Synchronously wait for the result
    var result workflows.OrderResult
    err = we.Get(context.Background(), &result)
    if err != nil {
        log.Fatalln("Workflow failed", err)
    }
    log.Printf("Workflow result: %+v\n", result)
}
```

### Sending a Signal

```go
// Signal from client
err = c.SignalWorkflow(
    context.Background(),
    "order-12345",        // Workflow ID
    "",                   // Run ID (empty = current run)
    "approve",            // Signal name
    ApproveInput{ApproverName: "Alice"},
)

// Signal-With-Start: signal if running, otherwise start + signal
_, err = c.SignalWithStartWorkflow(
    context.Background(),
    "order-12345",        // Workflow ID
    "approve",            // Signal name
    ApproveInput{ApproverName: "Alice"},  // Signal arg
    client.StartWorkflowOptions{
        TaskQueue: "my-task-queue",
    },
    workflows.ApprovalWorkflow,  // Workflow function
    orderInput,                  // Workflow arg
)
```

### Signal from Another Workflow

```go
// Inside a Workflow:
err := workflow.SignalExternalWorkflow(ctx, "target-workflow-id", "", "signal-name", signalData).Get(ctx, nil)
```

### Querying a Workflow

```go
result, err := c.QueryWorkflow(
    context.Background(),
    "order-12345",    // Workflow ID
    "",               // Run ID
    "get-state",      // Query type
    // Optional query args...
)
if err != nil {
    log.Fatalln("Query failed", err)
}
var state string
err = result.Get(&state)
```

### Sending an Update

```go
ctxWithTimeout, cancel := context.WithTimeout(context.Background(), 15*time.Second)
defer cancel()

updateHandle, err := c.UpdateWorkflow(ctxWithTimeout, client.UpdateWorkflowOptions{
    WorkflowID:   "counter-workflow-id",
    RunID:        "",                                       // empty = current run
    UpdateName:   "fetch_and_add",
    WaitForStage: client.WorkflowUpdateStageAccepted,       // or WorkflowUpdateStageCompleted
    Args:         []interface{}{5},
})
if err != nil {
    log.Fatalf("Update failed: %v", err)
}

var previousValue int
err = updateHandle.Get(ctxWithTimeout, &previousValue)
```

### Cancelling a Workflow

```go
err = c.CancelWorkflow(context.Background(), "order-12345", "")
```

## Error Handling

### Workflow Error Types

Handle different error types from Activity or Child Workflow failures:

```go
err := workflow.ExecuteActivity(ctx, a.DoSomething, input).Get(ctx, nil)
if err != nil {
    var applicationErr *temporal.ApplicationError
    if errors.As(err, &applicationErr) {
        // Application-level error (from Activity code)
        switch applicationErr.Type() {
        case "ValidationError":
            // Handle validation error
        case "NotFound":
            // Handle not found
        default:
            return err
        }
    }

    var canceledErr *temporal.CanceledError
    if errors.As(err, &canceledErr) {
        // Workflow or Activity was canceled
        return err
    }

    var timeoutErr *temporal.TimeoutError
    if errors.As(err, &timeoutErr) {
        switch timeoutErr.TimeoutType() {
        case enumspb.TIMEOUT_TYPE_START_TO_CLOSE:
            // Activity took too long
        case enumspb.TIMEOUT_TYPE_HEARTBEAT:
            // Activity stopped heartbeating
        case enumspb.TIMEOUT_TYPE_SCHEDULE_TO_START:
            // No Worker picked up the task
        }
    }

    var panicErr *temporal.PanicError
    if errors.As(err, &panicErr) {
        // Activity panicked -- panicErr.Error() and panicErr.StackTrace() available
    }
}
```

### Non-Retryable Errors

```go
// In Activity code: return a non-retryable error to stop retries immediately
return temporal.NewNonRetryableApplicationError(
    "invalid input: email is required",
    "ValidationError",
    nil, // cause
)

// In Workflow code: check specific error types in NonRetryableErrorTypes
ao := workflow.ActivityOptions{
    RetryPolicy: &temporal.RetryPolicy{
        NonRetryableErrorTypes: []string{"ValidationError", "NotFound"},
    },
}
```

## Retry Policies

### Activity Retry Policy

Activities retry by default. Customize with `temporal.RetryPolicy`:

```go
retryPolicy := &temporal.RetryPolicy{
    InitialInterval:        time.Second,       // First retry delay (default: 1s)
    BackoffCoefficient:     2.0,               // Multiplier for each retry (default: 2.0)
    MaximumInterval:        time.Minute,       // Cap on retry delay (default: 100x InitialInterval)
    MaximumAttempts:        5,                 // 0 = unlimited (default: 0)
    NonRetryableErrorTypes: []string{          // Error types that stop retries
        "ValidationError",
    },
}

ao := workflow.ActivityOptions{
    StartToCloseTimeout: 2 * time.Minute,
    HeartbeatTimeout:    10 * time.Second,
    RetryPolicy:         retryPolicy,
}
ctx = workflow.WithActivityOptions(ctx, ao)
```

### Workflow Retry Policy

Workflows do NOT retry by default. Add a retry policy when starting the Workflow:

```go
options := client.StartWorkflowOptions{
    ID:        "my-workflow",
    TaskQueue: "my-queue",
    RetryPolicy: &temporal.RetryPolicy{
        InitialInterval:    time.Second,
        BackoffCoefficient: 2.0,
        MaximumInterval:    100 * time.Second,
    },
}
```

## Activity Options Reference

```go
ao := workflow.ActivityOptions{
    // REQUIRED: at least one of these two must be set
    StartToCloseTimeout:    30 * time.Second,     // Max time for a single attempt
    ScheduleToCloseTimeout: 5 * time.Minute,      // Max total time including retries

    // OPTIONAL
    ScheduleToStartTimeout: time.Minute,           // Max time waiting for a Worker
    HeartbeatTimeout:       10 * time.Second,       // Must heartbeat within this interval
    TaskQueueName:          "special-queue",        // Override parent's task queue
    WaitForCancellation:    true,                   // Wait for Activity to handle cancellation
    RetryPolicy:            &temporal.RetryPolicy{},
    ActivityID:             "custom-id",
}
ctx = workflow.WithActivityOptions(ctx, ao)
```

## Testing

### Workflow Unit Tests with Mocked Activities

```go
package workflows_test

import (
    "testing"

    "github.com/stretchr/testify/mock"
    "github.com/stretchr/testify/require"
    "go.temporal.io/sdk/testsuite"
)

func Test_ProcessOrderWorkflow(t *testing.T) {
    testSuite := &testsuite.WorkflowTestSuite{}
    env := testSuite.NewTestWorkflowEnvironment()

    // Mock activities
    var a *Activities
    env.OnActivity(a.ChargePayment, mock.Anything, mock.Anything).Return(
        &PaymentResult{PaymentID: "pay-123", Status: "charged"}, nil,
    )
    env.OnActivity(a.ShipOrder, mock.Anything, mock.Anything).Return(
        &ShippingResult{TrackingCode: "TRACK-456"}, nil,
    )

    // Execute the workflow
    input := OrderInput{OrderID: "order-1", Amount: 99.99}
    env.ExecuteWorkflow(ProcessOrder, input)

    // Assert
    require.True(t, env.IsWorkflowCompleted())
    require.NoError(t, env.GetWorkflowError())

    var result OrderResult
    require.NoError(t, env.GetWorkflowResult(&result))
    require.Equal(t, "pay-123", result.PaymentID)
    require.Equal(t, "TRACK-456", result.TrackingCode)
}
```

### Test Activity Failure

```go
func Test_ProcessOrder_PaymentFails(t *testing.T) {
    testSuite := &testsuite.WorkflowTestSuite{}
    env := testSuite.NewTestWorkflowEnvironment()

    var a *Activities
    env.OnActivity(a.ChargePayment, mock.Anything, mock.Anything).Return(
        nil, temporal.NewApplicationError("payment declined", "PaymentError"),
    )

    env.ExecuteWorkflow(ProcessOrder, OrderInput{OrderID: "order-1"})

    require.True(t, env.IsWorkflowCompleted())
    err := env.GetWorkflowError()
    require.Error(t, err)

    var appErr *temporal.ApplicationError
    require.True(t, errors.As(err, &appErr))
    require.Equal(t, "PaymentError", appErr.Type())
}
```

### Mock with Custom Implementation

```go
func Test_ProcessOrder_ValidatesInput(t *testing.T) {
    testSuite := &testsuite.WorkflowTestSuite{}
    env := testSuite.NewTestWorkflowEnvironment()

    var a *Activities
    env.OnActivity(a.ChargePayment, mock.Anything, mock.Anything).Return(
        func(ctx context.Context, input PaymentInput) (*PaymentResult, error) {
            // Custom implementation that validates the input
            require.Equal(t, "order-1", input.OrderID)
            require.Equal(t, 99.99, input.Amount)
            return &PaymentResult{PaymentID: "pay-123"}, nil
        },
    )

    env.OnActivity(a.ShipOrder, mock.Anything, mock.Anything).Return(
        &ShippingResult{TrackingCode: "TRACK-456"}, nil,
    )

    env.ExecuteWorkflow(ProcessOrder, OrderInput{OrderID: "order-1", Amount: 99.99})
    require.True(t, env.IsWorkflowCompleted())
    require.NoError(t, env.GetWorkflowError())
}
```

### Activity Unit Tests

```go
func Test_ChargePayment(t *testing.T) {
    testSuite := &testsuite.WorkflowTestSuite{}
    env := testSuite.NewTestActivityEnvironment()

    a := &Activities{
        APIClient: mockHTTPClient,
        Config:    testConfig,
    }
    env.RegisterActivity(a)

    result, err := env.ExecuteActivity(a.ChargePayment, PaymentInput{
        OrderID: "order-1",
        Amount:  50.00,
    })

    require.NoError(t, err)
    var paymentResult PaymentResult
    require.NoError(t, result.Get(&paymentResult))
    require.Equal(t, "charged", paymentResult.Status)
}
```

### Test with Signals

```go
func Test_ApprovalWorkflow_WithSignal(t *testing.T) {
    testSuite := &testsuite.WorkflowTestSuite{}
    env := testSuite.NewTestWorkflowEnvironment()

    // Send signal after a delay
    env.RegisterDelayedCallback(func() {
        env.SignalWorkflow("approve", ApproveInput{ApproverName: "Alice"})
    }, time.Millisecond*10)

    env.ExecuteWorkflow(ApprovalWorkflow, "order-1")

    require.True(t, env.IsWorkflowCompleted())
    require.NoError(t, env.GetWorkflowError())
}
```

### Test with Queries

```go
func Test_QueryableWorkflow(t *testing.T) {
    testSuite := &testsuite.WorkflowTestSuite{}
    env := testSuite.NewTestWorkflowEnvironment()

    env.RegisterDelayedCallback(func() {
        result, err := env.QueryWorkflow("get-state")
        require.NoError(t, err)
        var state string
        require.NoError(t, result.Get(&state))
        require.Equal(t, "processing", state)
    }, time.Millisecond*10)

    env.ExecuteWorkflow(QueryableWorkflow)
}
```

### Integration Tests with Dev Server

```go
func Test_Integration_WithDevServer(t *testing.T) {
    server, err := testsuite.StartDevServer(context.Background(), testsuite.DevServerOptions{
        ClientOptions: &client.Options{HostPort: ""}, // random port
    })
    require.NoError(t, err)
    defer func() { _ = server.Stop() }()

    c := server.Client()
    taskQueue := "integration-test-queue"

    // Start worker in background
    w := worker.New(c, taskQueue, worker.Options{})
    w.RegisterWorkflow(ProcessOrder)
    w.RegisterActivity(&Activities{/* deps */})

    go func() { _ = w.Run(worker.InterruptCh()) }()
    defer w.Stop()

    // Execute workflow
    we, err := c.ExecuteWorkflow(context.Background(), client.StartWorkflowOptions{
        ID:        "test-order-1",
        TaskQueue: taskQueue,
    }, ProcessOrder, OrderInput{OrderID: "test-1", Amount: 50.00})
    require.NoError(t, err)

    var result OrderResult
    err = we.Get(context.Background(), &result)
    require.NoError(t, err)
    require.Equal(t, "test-1", result.OrderID)
}
```

### Test Suite Pattern (testify suite)

```go
type OrderWorkflowSuite struct {
    suite.Suite
    testsuite.WorkflowTestSuite
    env *testsuite.TestWorkflowEnvironment
}

func (s *OrderWorkflowSuite) SetupTest() {
    s.env = s.NewTestWorkflowEnvironment()
}

func (s *OrderWorkflowSuite) AfterTest(suiteName, testName string) {
    s.env.AssertExpectations(s.T())
}

func (s *OrderWorkflowSuite) Test_HappyPath() {
    var a *Activities
    s.env.OnActivity(a.ChargePayment, mock.Anything, mock.Anything).Return(
        &PaymentResult{PaymentID: "p1"}, nil,
    )
    s.env.OnActivity(a.ShipOrder, mock.Anything, mock.Anything).Return(
        &ShippingResult{TrackingCode: "t1"}, nil,
    )

    s.env.ExecuteWorkflow(ProcessOrder, OrderInput{OrderID: "1"})
    s.True(s.env.IsWorkflowCompleted())
    s.NoError(s.env.GetWorkflowError())
}

func TestOrderWorkflowSuite(t *testing.T) {
    suite.Run(t, new(OrderWorkflowSuite))
}
```

## Key Patterns

### Saga / Compensation Pattern

Use Go's `defer` to build compensation logic. If a later step fails, earlier steps are automatically compensated in reverse order.

```go
func TransferMoney(ctx workflow.Context, details TransferDetails) (err error) {
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: time.Minute,
        RetryPolicy: &temporal.RetryPolicy{
            InitialInterval:    time.Second,
            BackoffCoefficient: 2.0,
            MaximumInterval:    time.Minute,
            MaximumAttempts:    3,
        },
    }
    ctx = workflow.WithActivityOptions(ctx, ao)

    // Step 1: Withdraw
    err = workflow.ExecuteActivity(ctx, Withdraw, details).Get(ctx, nil)
    if err != nil {
        return err
    }

    // Compensate Step 1 if later steps fail
    defer func() {
        if err != nil {
            errCompensation := workflow.ExecuteActivity(ctx, WithdrawCompensation, details).Get(ctx, nil)
            err = multierr.Append(err, errCompensation)
        }
    }()

    // Step 2: Deposit
    err = workflow.ExecuteActivity(ctx, Deposit, details).Get(ctx, nil)
    if err != nil {
        return err  // triggers WithdrawCompensation via defer
    }

    // Compensate Step 2 if later steps fail
    defer func() {
        if err != nil {
            errCompensation := workflow.ExecuteActivity(ctx, DepositCompensation, details).Get(ctx, nil)
            err = multierr.Append(err, errCompensation)
        }
    }()

    // Step 3: Notify (if this fails, both Deposit and Withdraw are compensated)
    err = workflow.ExecuteActivity(ctx, SendNotification, details).Get(ctx, nil)
    if err != nil {
        return err  // triggers DepositCompensation then WithdrawCompensation
    }

    return nil
}
```

### Cancellation with Cleanup

When a Workflow is canceled, use `workflow.NewDisconnectedContext` to run cleanup Activities:

```go
func CancellableWorkflow(ctx workflow.Context) error {
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: 30 * time.Minute,
        HeartbeatTimeout:    5 * time.Second,
        WaitForCancellation: true,  // Wait for Activity to acknowledge cancel
    }
    ctx = workflow.WithActivityOptions(ctx, ao)

    // Cleanup runs even after cancellation
    defer func() {
        if !errors.Is(ctx.Err(), workflow.ErrCanceled) {
            return
        }
        // Get a new context that is NOT canceled
        newCtx, _ := workflow.NewDisconnectedContext(ctx)
        err := workflow.ExecuteActivity(newCtx, CleanupActivity).Get(newCtx, nil)
        if err != nil {
            workflow.GetLogger(ctx).Error("Cleanup failed", "Error", err)
        }
    }()

    // Long-running activity that can be canceled
    var result string
    err := workflow.ExecuteActivity(ctx, LongRunningActivity).Get(ctx, &result)
    return err
}
```

### Polling Pattern: Frequent (Activity with Heartbeat)

Poll inside a single long-running Activity using heartbeats:

```go
// Activity: polls until success, heartbeating to stay alive
func PollForResult(ctx context.Context) (string, error) {
    for {
        result, err := callExternalService(ctx)
        if err == nil {
            return result, nil
        }

        activity.RecordHeartbeat(ctx)

        select {
        case <-ctx.Done():
            return "", ctx.Err()
        case <-time.After(5 * time.Second):
            // poll again
        }
    }
}

// Workflow: use long timeout + heartbeat
func PollingWorkflow(ctx workflow.Context) (string, error) {
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: 24 * time.Hour,
        HeartbeatTimeout:    30 * time.Second,
    }
    ctx = workflow.WithActivityOptions(ctx, ao)

    var result string
    err := workflow.ExecuteActivity(ctx, PollForResult).Get(ctx, &result)
    return result, err
}
```

### Polling Pattern: Infrequent (Activity Retries)

Use the retry policy itself as the polling mechanism:

```go
func InfrequentPollingWorkflow(ctx workflow.Context) (string, error) {
    ao := workflow.ActivityOptions{
        StartToCloseTimeout: 2 * time.Second,  // Short: just check once
        RetryPolicy: &temporal.RetryPolicy{
            BackoffCoefficient: 1,              // Constant interval
            InitialInterval:    60 * time.Second, // Poll every 60s
            // MaximumAttempts: 0 means unlimited retries
        },
    }
    ctx = workflow.WithActivityOptions(ctx, ao)

    var result string
    err := workflow.ExecuteActivity(ctx, CheckService).Get(ctx, &result)
    return result, err
}

// Activity: check once and return error if not ready
func CheckService(ctx context.Context) (string, error) {
    result, err := callExternalService(ctx)
    if err != nil {
        return "", err  // Will be retried per RetryPolicy
    }
    return result, nil
}
```

### Parallel Activities with Futures

Launch multiple Activities in parallel and collect results:

```go
func ParallelWorkflow(ctx workflow.Context, items []string) ([]Result, error) {
    ao := workflow.ActivityOptions{StartToCloseTimeout: 10 * time.Second}
    ctx = workflow.WithActivityOptions(ctx, ao)

    // Launch all activities
    var futures []workflow.Future
    for _, item := range items {
        future := workflow.ExecuteActivity(ctx, ProcessItem, item)
        futures = append(futures, future)
    }

    // Collect results (in order)
    var results []Result
    for _, future := range futures {
        var result Result
        if err := future.Get(ctx, &result); err != nil {
            return nil, err
        }
        results = append(results, result)
    }
    return results, nil
}
```

### Process Results as They Complete (Selector)

```go
func ProcessAsCompleted(ctx workflow.Context, items []string) error {
    ao := workflow.ActivityOptions{StartToCloseTimeout: 10 * time.Second}
    ctx = workflow.WithActivityOptions(ctx, ao)

    selector := workflow.NewSelector(ctx)
    var processErr error

    for _, item := range items {
        future := workflow.ExecuteActivity(ctx, ProcessItem, item)
        selector.AddFuture(future, func(f workflow.Future) {
            var result Result
            if err := f.Get(ctx, &result); err != nil {
                processErr = err
                return
            }
            // Process result immediately as it arrives
            workflow.GetLogger(ctx).Info("Got result", "value", result)
        })
    }

    // Wait for all
    for range items {
        selector.Select(ctx)
        if processErr != nil {
            return processErr
        }
    }
    return nil
}
```

### Updatable Timer

A timer that can be rescheduled via Signals:

```go
type UpdatableTimer struct {
    wakeUpTime time.Time
}

func (u *UpdatableTimer) SleepUntil(ctx workflow.Context, wakeUpTime time.Time, updateCh workflow.ReceiveChannel) error {
    u.wakeUpTime = wakeUpTime
    timerFired := false

    for !timerFired && ctx.Err() == nil {
        timerCtx, timerCancel := workflow.WithCancel(ctx)
        duration := u.wakeUpTime.Sub(workflow.Now(timerCtx))
        timer := workflow.NewTimer(timerCtx, duration)

        workflow.NewSelector(timerCtx).
            AddFuture(timer, func(f workflow.Future) {
                if f.Get(timerCtx, nil) == nil {
                    timerFired = true
                }
            }).
            AddReceive(updateCh, func(c workflow.ReceiveChannel, more bool) {
                timerCancel()                         // cancel current timer
                c.Receive(timerCtx, &u.wakeUpTime)    // update to new time
            }).
            Select(timerCtx)
    }
    return ctx.Err()
}

func ReminderWorkflow(ctx workflow.Context, initialTime time.Time) error {
    timer := UpdatableTimer{}

    err := workflow.SetQueryHandler(ctx, "getWakeUpTime", func() (time.Time, error) {
        return timer.wakeUpTime, nil
    })
    if err != nil {
        return err
    }

    return timer.SleepUntil(ctx, initialTime, workflow.GetSignalChannel(ctx, "updateWakeUpTime"))
}
```

### Ordered Signal Processing with Await

Process signals that may arrive out of order:

```go
type SignalTracker struct {
    Signal1Received bool
    Signal2Received bool
    Signal3Received bool
    FirstSignalTime time.Time
}

func (s *SignalTracker) Listen(ctx workflow.Context) {
    for {
        selector := workflow.NewSelector(ctx)
        selector.AddReceive(workflow.GetSignalChannel(ctx, "Signal1"), func(c workflow.ReceiveChannel, more bool) {
            c.Receive(ctx, nil)
            s.Signal1Received = true
        })
        selector.AddReceive(workflow.GetSignalChannel(ctx, "Signal2"), func(c workflow.ReceiveChannel, more bool) {
            c.Receive(ctx, nil)
            s.Signal2Received = true
        })
        selector.AddReceive(workflow.GetSignalChannel(ctx, "Signal3"), func(c workflow.ReceiveChannel, more bool) {
            c.Receive(ctx, nil)
            s.Signal3Received = true
        })
        selector.Select(ctx)
        if s.FirstSignalTime.IsZero() {
            s.FirstSignalTime = workflow.Now(ctx)
        }
    }
}

func OrderedSignalsWorkflow(ctx workflow.Context) error {
    var tracker SignalTracker

    // Listen for signals in background goroutine
    workflow.Go(ctx, tracker.Listen)

    // Wait for Signal1 first
    err := workflow.Await(ctx, func() bool { return tracker.Signal1Received })
    if err != nil {
        return err
    }

    // Wait for Signal2 with timeout
    ok, err := workflow.AwaitWithTimeout(ctx, 30*time.Second, func() bool {
        return tracker.Signal2Received
    })
    if err != nil {
        return err
    }
    if !ok {
        return temporal.NewApplicationError("timed out waiting for Signal2", "timeout")
    }

    // Wait for Signal3 with timeout
    ok, err = workflow.AwaitWithTimeout(ctx, 30*time.Second, func() bool {
        return tracker.Signal3Received
    })
    if err != nil {
        return err
    }
    if !ok {
        return temporal.NewApplicationError("timed out waiting for Signal3", "timeout")
    }

    return nil
}
```

## Workflow Info

Access metadata about the current Workflow Execution:

```go
info := workflow.GetInfo(ctx)
info.WorkflowExecution.ID        // Workflow ID
info.WorkflowExecution.RunID     // Run ID
info.WorkflowType.Name           // Workflow type name
info.TaskQueueName               // Task Queue
info.Attempt                     // Current attempt (starts at 1)
info.GetContinueAsNewSuggested() // True when history is getting large
info.GetCurrentHistoryLength()   // Current history event count
```

## DeterministicKeys

When iterating over maps in Workflow code, always use `workflow.DeterministicKeys` to get a sorted, deterministic key order:

```go
myMap := map[string]string{"b": "2", "a": "1", "c": "3"}

// WRONG: range over map is non-deterministic
// for k, v := range myMap { ... }

// CORRECT: use DeterministicKeys
for _, k := range workflow.DeterministicKeys(myMap) {
    v := myMap[k]
    // process k, v
}
```
