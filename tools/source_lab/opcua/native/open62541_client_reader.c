#define _POSIX_C_SOURCE 200809L

#include <open62541/client.h>
#include <open62541/client_config_default.h>

#include <errno.h>
#include <poll.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_LINE_LEN 8192

typedef struct PreparedPlan {
    char *plan_id;
    UA_NodeId *node_ids;
    size_t node_count;
    struct PreparedPlan *next;
} PreparedPlan;

typedef struct AppContext {
    UA_Client *client;
    UA_UInt16 namespace_index;
    PreparedPlan *plans;
} AppContext;

typedef struct ReadExecutionResult {
    bool success;
    size_t value_count;
    int64_t response_timestamp_ms;
    const char *detail;
    int64_t read_start_ts_ns;
    int64_t read_end_ts_ns;
} ReadExecutionResult;

typedef enum PollControlAction {
    POLL_CONTROL_NONE = 0,
    POLL_CONTROL_STOP = 1,
    POLL_CONTROL_QUIT = 2,
} PollControlAction;

static char *xstrdup(const char *value) {
    size_t len = strlen(value);
    char *copy = (char *)malloc(len + 1);
    if(copy == NULL) {
        return NULL;
    }
    memcpy(copy, value, len + 1);
    return copy;
}

static void strip_newline(char *line) {
    size_t len = strlen(line);
    while(len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
        line[len - 1] = '\0';
        len--;
    }
}

static int split_fields(char *line, char **fields, int max_fields) {
    int count = 0;
    char *cursor = line;

    while(cursor != NULL && count < max_fields) {
        fields[count++] = cursor;
        char *tab = strchr(cursor, '\t');
        if(tab == NULL) {
            break;
        }
        *tab = '\0';
        cursor = tab + 1;
    }

    return count;
}

static int64_t ua_datetime_to_unix_ms(UA_DateTime value) {
    if(value <= 0) {
        return 0;
    }
    return (int64_t)((value - UA_DATETIME_UNIX_EPOCH) / UA_DATETIME_MSEC);
}

static int64_t monotonic_now_ns(void) {
    struct timespec ts;
    if(clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return ((int64_t)ts.tv_sec * 1000000000LL) + (int64_t)ts.tv_nsec;
}

static void print_result_line(
    const char *plan_id,
    const char *status,
    size_t value_count,
    int64_t response_timestamp_ms,
    const char *detail,
    int64_t request_received_ts_ns,
    int64_t read_start_ts_ns,
    int64_t read_end_ts_ns
) {
    int64_t response_write_ts_ns = monotonic_now_ns();
    printf(
        "RESULT\t%s\t%s\t%zu\t%lld\t%s\t%lld\t%lld\t%lld\t%lld\n",
        plan_id,
        status,
        value_count,
        (long long)response_timestamp_ms,
        detail == NULL || detail[0] == '\0' ? "-" : detail,
        (long long)request_received_ts_ns,
        (long long)read_start_ts_ns,
        (long long)read_end_ts_ns,
        (long long)response_write_ts_ns
    );
    fflush(stdout);
}

static void print_stream_result_line(
    const char *plan_id,
    int64_t seq,
    const char *status,
    size_t value_count,
    int64_t response_timestamp_ms,
    const char *detail,
    int64_t scheduled_ts_ns,
    int64_t read_start_ts_ns,
    int64_t read_end_ts_ns
) {
    int64_t response_write_ts_ns = monotonic_now_ns();
    printf(
        "RESULT_STREAM\t%s\t%lld\t%s\t%zu\t%lld\t%s\t%lld\t%lld\t%lld\t%lld\n",
        plan_id,
        (long long)seq,
        status,
        value_count,
        (long long)response_timestamp_ms,
        detail == NULL || detail[0] == '\0' ? "-" : detail,
        (long long)scheduled_ts_ns,
        (long long)read_start_ts_ns,
        (long long)read_end_ts_ns,
        (long long)response_write_ts_ns
    );
    fflush(stdout);
}

static void clear_plan(PreparedPlan *plan) {
    if(plan == NULL) {
        return;
    }

    free(plan->plan_id);
    if(plan->node_ids != NULL) {
        for(size_t i = 0; i < plan->node_count; ++i) {
            UA_NodeId_clear(&plan->node_ids[i]);
        }
        free(plan->node_ids);
    }

    plan->plan_id = NULL;
    plan->node_ids = NULL;
    plan->node_count = 0;
}

static void free_plans(PreparedPlan *plan) {
    while(plan != NULL) {
        PreparedPlan *next = plan->next;
        clear_plan(plan);
        free(plan);
        plan = next;
    }
}

static PreparedPlan *find_plan(AppContext *app, const char *plan_id) {
    PreparedPlan *plan = app->plans;
    while(plan != NULL) {
        if(strcmp(plan->plan_id, plan_id) == 0) {
            return plan;
        }
        plan = plan->next;
    }
    return NULL;
}

static UA_StatusCode parse_or_build_node_id(
    const char *text,
    UA_UInt16 namespace_index,
    UA_NodeId *node_id
) {
    UA_NodeId_init(node_id);

    if(
        strncmp(text, "ns=", 3) == 0 ||
        strncmp(text, "nsu=", 4) == 0 ||
        strncmp(text, "s=", 2) == 0 ||
        strncmp(text, "i=", 2) == 0 ||
        strncmp(text, "g=", 2) == 0 ||
        strncmp(text, "b=", 2) == 0
    ) {
        return UA_NodeId_parse(node_id, UA_STRING((char *)(uintptr_t)text));
    }

    *node_id = UA_NODEID_STRING_ALLOC(namespace_index, text);
    return UA_NodeId_isNull(node_id) ? UA_STATUSCODE_BADOUTOFMEMORY : UA_STATUSCODE_GOOD;
}

static bool load_plan_nodes(
    const char *path,
    UA_UInt16 namespace_index,
    UA_NodeId **node_ids_out,
    size_t *node_count_out,
    char *error,
    size_t error_size
) {
    FILE *fp = fopen(path, "r");
    if(fp == NULL) {
        snprintf(error, error_size, "failed to open node file: %s", path);
        return false;
    }

    size_t capacity = 16;
    size_t count = 0;
    UA_NodeId *node_ids = (UA_NodeId *)calloc(capacity, sizeof(UA_NodeId));
    if(node_ids == NULL) {
        fclose(fp);
        snprintf(error, error_size, "failed to allocate node id array");
        return false;
    }

    char line[MAX_LINE_LEN];
    while(fgets(line, sizeof(line), fp) != NULL) {
        strip_newline(line);
        if(line[0] == '\0') {
            continue;
        }

        if(count == capacity) {
            size_t next_capacity = capacity * 2;
            UA_NodeId *resized = (UA_NodeId *)realloc(node_ids, next_capacity * sizeof(UA_NodeId));
            if(resized == NULL) {
                snprintf(error, error_size, "failed to resize node id array");
                goto fail;
            }
            node_ids = resized;
            memset(node_ids + capacity, 0, (next_capacity - capacity) * sizeof(UA_NodeId));
            capacity = next_capacity;
        }

        UA_StatusCode status = parse_or_build_node_id(line, namespace_index, &node_ids[count]);
        if(status != UA_STATUSCODE_GOOD) {
            snprintf(
                error,
                error_size,
                "failed to parse node id %s: %s",
                line,
                UA_StatusCode_name(status)
            );
            goto fail;
        }

        count++;
    }

    fclose(fp);

    *node_ids_out = node_ids;
    *node_count_out = count;
    return true;

fail:
    fclose(fp);
    for(size_t i = 0; i < count; ++i) {
        UA_NodeId_clear(&node_ids[i]);
    }
    free(node_ids);
    return false;
}

static bool handle_prepare(
    AppContext *app,
    const char *plan_id,
    const char *file_path
) {
    char error[512] = {0};
    UA_NodeId *node_ids = NULL;
    size_t node_count = 0;

    if(!load_plan_nodes(file_path, app->namespace_index, &node_ids, &node_count, error, sizeof(error))) {
        printf("ERROR\tprepare\t%s\n", error);
        fflush(stdout);
        return false;
    }

    PreparedPlan *plan = find_plan(app, plan_id);
    if(plan == NULL) {
        plan = (PreparedPlan *)calloc(1, sizeof(PreparedPlan));
        if(plan == NULL) {
            for(size_t i = 0; i < node_count; ++i) {
                UA_NodeId_clear(&node_ids[i]);
            }
            free(node_ids);
            printf("ERROR\tprepare\tfailed to allocate plan\n");
            fflush(stdout);
            return false;
        }
        plan->plan_id = xstrdup(plan_id);
        if(plan->plan_id == NULL) {
            free(plan);
            for(size_t i = 0; i < node_count; ++i) {
                UA_NodeId_clear(&node_ids[i]);
            }
            free(node_ids);
            printf("ERROR\tprepare\tfailed to allocate plan id\n");
            fflush(stdout);
            return false;
        }
        plan->next = app->plans;
        app->plans = plan;
    } else {
        clear_plan(plan);
        plan->plan_id = xstrdup(plan_id);
        if(plan->plan_id == NULL) {
            for(size_t i = 0; i < node_count; ++i) {
                UA_NodeId_clear(&node_ids[i]);
            }
            free(node_ids);
            printf("ERROR\tprepare\tfailed to reset plan id\n");
            fflush(stdout);
            return false;
        }
    }

    plan->node_ids = node_ids;
    plan->node_count = node_count;

    printf("PREPARED\t%s\t%zu\n", plan_id, node_count);
    fflush(stdout);
    return true;
}

static bool execute_read_plan(
    AppContext *app,
    PreparedPlan *plan,
    ReadExecutionResult *result
) {
    UA_ReadValueId *nodes_to_read =
        (UA_ReadValueId *)calloc(plan->node_count, sizeof(UA_ReadValueId));
    if(nodes_to_read == NULL) {
        result->success = false;
        result->value_count = 0;
        result->response_timestamp_ms = 0;
        result->detail = "alloc_failed";
        result->read_start_ts_ns = 0;
        result->read_end_ts_ns = 0;
        return false;
    }

    bool ok = true;
    for(size_t i = 0; i < plan->node_count; ++i) {
        UA_ReadValueId_init(&nodes_to_read[i]);
        UA_StatusCode status = UA_NodeId_copy(&plan->node_ids[i], &nodes_to_read[i].nodeId);
        if(status != UA_STATUSCODE_GOOD) {
            ok = false;
            break;
        }
        nodes_to_read[i].attributeId = UA_ATTRIBUTEID_VALUE;
    }

    if(!ok) {
        for(size_t i = 0; i < plan->node_count; ++i) {
            UA_ReadValueId_clear(&nodes_to_read[i]);
        }
        free(nodes_to_read);
        result->success = false;
        result->value_count = 0;
        result->response_timestamp_ms = 0;
        result->detail = "nodeid_copy_failed";
        result->read_start_ts_ns = 0;
        result->read_end_ts_ns = 0;
        return false;
    }

    UA_ReadRequest request;
    UA_ReadRequest_init(&request);
    request.nodesToRead = nodes_to_read;
    request.nodesToReadSize = plan->node_count;
    request.timestampsToReturn = UA_TIMESTAMPSTORETURN_BOTH;

    int64_t read_start_ts_ns = monotonic_now_ns();
    UA_ReadResponse response = UA_Client_Service_read(app->client, request);
    int64_t read_end_ts_ns = monotonic_now_ns();
    size_t value_count = 0;
    bool success = response.responseHeader.serviceResult == UA_STATUSCODE_GOOD;
    if(success) {
        for(size_t i = 0; i < response.resultsSize; ++i) {
            const UA_DataValue *value = &response.results[i];
            if(value->hasValue && value->value.type != NULL) {
                value_count++;
            }
        }
    }

    int64_t response_timestamp_ms = ua_datetime_to_unix_ms(response.responseHeader.timestamp);
    result->success = success;
    result->value_count = success ? value_count : 0;
    result->response_timestamp_ms = response_timestamp_ms;
    result->detail = success ? "-" : UA_StatusCode_name(response.responseHeader.serviceResult);
    result->read_start_ts_ns = read_start_ts_ns;
    result->read_end_ts_ns = read_end_ts_ns;

    UA_ReadResponse_clear(&response);
    UA_ReadRequest_clear(&request);
    return success;
}

static bool handle_read(AppContext *app, const char *plan_id, int64_t request_received_ts_ns) {
    PreparedPlan *plan = find_plan(app, plan_id);
    ReadExecutionResult result;

    if(plan == NULL) {
        print_result_line(plan_id, "ERROR", 0, 0, "unknown_plan", request_received_ts_ns, 0, 0);
        return false;
    }

    execute_read_plan(app, plan, &result);
    print_result_line(
        plan_id,
        result.success ? "OK" : "ERROR",
        result.value_count,
        result.response_timestamp_ms,
        result.detail,
        request_received_ts_ns,
        result.read_start_ts_ns,
        result.read_end_ts_ns
    );
    return result.success;
}

static PollControlAction poll_for_stream_command(
    const char *active_plan_id,
    int timeout_ms
) {
    struct pollfd poll_fd = {
        .fd = 0,
        .events = POLLIN,
        .revents = 0,
    };

    int poll_result = poll(&poll_fd, 1, timeout_ms);
    if(poll_result <= 0 || (poll_fd.revents & POLLIN) == 0) {
        return POLL_CONTROL_NONE;
    }

    char line[MAX_LINE_LEN];
    if(fgets(line, sizeof(line), stdin) == NULL) {
        return POLL_CONTROL_QUIT;
    }

    strip_newline(line);
    if(line[0] == '\0') {
        return POLL_CONTROL_NONE;
    }

    char *fields[5] = {0};
    int field_count = split_fields(line, fields, 5);
    if(field_count <= 0) {
        return POLL_CONTROL_NONE;
    }

    if(strcmp(fields[0], "QUIT") == 0) {
        return POLL_CONTROL_QUIT;
    }

    if(strcmp(fields[0], "STOP_POLL") == 0) {
        if(field_count != 2) {
            printf("ERROR\tstop_poll\tinvalid_stop_poll_command\n");
            fflush(stdout);
            return POLL_CONTROL_NONE;
        }
        if(strcmp(fields[1], active_plan_id) != 0) {
            printf("ERROR\tstop_poll\tplan_id_mismatch\n");
            fflush(stdout);
            return POLL_CONTROL_NONE;
        }
        return POLL_CONTROL_STOP;
    }

    printf("ERROR\tcommand\tunsupported_during_poll\n");
    fflush(stdout);
    return POLL_CONTROL_NONE;
}

static PollControlAction wait_until_scheduled_or_command(
    const char *active_plan_id,
    int64_t scheduled_ts_ns
) {
    while(true) {
        int64_t now_ns = monotonic_now_ns();
        int64_t remaining_ns = scheduled_ts_ns - now_ns;
        if(remaining_ns <= 0) {
            return POLL_CONTROL_NONE;
        }

        if(remaining_ns > 2000000LL) {
            int64_t sleep_ns = remaining_ns - 1000000LL;
            int timeout_ms = (int)(sleep_ns / 1000000LL);
            if(timeout_ms > 50) {
                timeout_ms = 50;
            }
            PollControlAction action = poll_for_stream_command(active_plan_id, timeout_ms);
            if(action != POLL_CONTROL_NONE) {
                return action;
            }
            continue;
        }

        if(remaining_ns > 200000LL) {
            struct timespec sleep_ts = {
                .tv_sec = 0,
                .tv_nsec = remaining_ns - 100000LL,
            };
            nanosleep(&sleep_ts, NULL);
            continue;
        }

        sched_yield();
    }
}

static bool handle_start_poll(
    AppContext *app,
    const char *plan_id,
    const char *target_hz_text,
    const char *warmup_s_text,
    const char *duration_s_text,
    bool *quit_requested
) {
    PreparedPlan *plan = find_plan(app, plan_id);
    if(plan == NULL) {
        printf("ERROR\tstart_poll\tunknown_plan\n");
        fflush(stdout);
        return false;
    }

    char *endptr = NULL;
    double target_hz = strtod(target_hz_text, &endptr);
    if(endptr == target_hz_text || target_hz <= 0.0) {
        printf("ERROR\tstart_poll\tinvalid_target_hz\n");
        fflush(stdout);
        return false;
    }

    endptr = NULL;
    double warmup_s = strtod(warmup_s_text, &endptr);
    if(endptr == warmup_s_text || warmup_s < 0.0) {
        printf("ERROR\tstart_poll\tinvalid_warmup_s\n");
        fflush(stdout);
        return false;
    }

    endptr = NULL;
    double duration_s = strtod(duration_s_text, &endptr);
    if(endptr == duration_s_text || duration_s <= 0.0) {
        printf("ERROR\tstart_poll\tinvalid_duration_s\n");
        fflush(stdout);
        return false;
    }

    int64_t interval_ns = (int64_t)(1000000000.0 / target_hz);
    if(interval_ns <= 0) {
        interval_ns = 1;
    }
    int64_t total_duration_ns = (int64_t)((warmup_s + duration_s) * 1000000000.0);
    if(total_duration_ns <= 0) {
        printf("ERROR\tstart_poll\tinvalid_total_duration\n");
        fflush(stdout);
        return false;
    }

    int64_t base_time_ns = monotonic_now_ns();
    int64_t end_time_ns = base_time_ns + total_duration_ns;
    int64_t seq = 0;
    int64_t ok_count = 0;
    int64_t error_count = 0;

    printf(
        "POLL_STARTED\t%s\t%s\t%s\t%s\n",
        plan_id,
        target_hz_text,
        warmup_s_text,
        duration_s_text
    );
    fflush(stdout);

    while(true) {
        int64_t scheduled_ts_ns = base_time_ns + (seq * interval_ns);
        if(scheduled_ts_ns >= end_time_ns) {
            break;
        }

        PollControlAction action = wait_until_scheduled_or_command(plan_id, scheduled_ts_ns);
        if(action == POLL_CONTROL_QUIT) {
            *quit_requested = true;
            return false;
        }
        if(action == POLL_CONTROL_STOP) {
            printf(
                "POLL_STOPPED\t%s\t%lld\t%lld\t%lld\n",
                plan_id,
                (long long)seq,
                (long long)ok_count,
                (long long)error_count
            );
            fflush(stdout);
            return true;
        }

        ReadExecutionResult result;
        execute_read_plan(app, plan, &result);
        print_stream_result_line(
            plan_id,
            seq,
            result.success ? "OK" : "ERROR",
            result.value_count,
            result.response_timestamp_ms,
            result.detail,
            scheduled_ts_ns,
            result.read_start_ts_ns,
            result.read_end_ts_ns
        );
        if(result.success) {
            ok_count++;
        } else {
            error_count++;
        }
        seq++;
    }

    printf(
        "POLL_DONE\t%s\t%lld\t%lld\t%lld\n",
        plan_id,
        (long long)seq,
        (long long)ok_count,
        (long long)error_count
    );
    fflush(stdout);
    return true;
}

static int run_loop(AppContext *app) {
    char line[MAX_LINE_LEN];

    while(fgets(line, sizeof(line), stdin) != NULL) {
        int64_t request_received_ts_ns = monotonic_now_ns();
        strip_newline(line);
        if(line[0] == '\0') {
            continue;
        }

        char *fields[5] = {0};
        int field_count = split_fields(line, fields, 5);
        if(field_count <= 0) {
            continue;
        }

        if(strcmp(fields[0], "QUIT") == 0) {
            return 0;
        }

        if(strcmp(fields[0], "PREPARE") == 0) {
            if(field_count != 3) {
                printf("ERROR\tprepare\tinvalid_prepare_command\n");
                fflush(stdout);
                continue;
            }
            handle_prepare(app, fields[1], fields[2]);
            continue;
        }

        if(strcmp(fields[0], "READ") == 0) {
            if(field_count != 2) {
                print_result_line("-", "ERROR", 0, 0, "invalid_read_command", request_received_ts_ns, 0, 0);
                continue;
            }
            handle_read(app, fields[1], request_received_ts_ns);
            continue;
        }

        if(strcmp(fields[0], "START_POLL") == 0) {
            if(field_count != 5) {
                printf("ERROR\tstart_poll\tinvalid_start_poll_command\n");
                fflush(stdout);
                continue;
            }
            bool quit_requested = false;
            handle_start_poll(app, fields[1], fields[2], fields[3], fields[4], &quit_requested);
            if(quit_requested) {
                return 0;
            }
            continue;
        }

        if(strcmp(fields[0], "STOP_POLL") == 0) {
            printf("ERROR\tstop_poll\tno_active_poll\n");
            fflush(stdout);
            continue;
        }

        printf("ERROR\tcommand\tunknown_command\n");
        fflush(stdout);
    }

    return 0;
}

int main(int argc, char **argv) {
    if(argc != 4) {
        fprintf(stderr, "usage: %s <endpoint> <namespace_uri_or_dash> <timeout_ms>\n", argv[0]);
        return 2;
    }

    const char *endpoint = argv[1];
    const char *namespace_uri_arg = argv[2];
    const char *timeout_arg = argv[3];
    const char *namespace_uri = strcmp(namespace_uri_arg, "-") == 0 ? NULL : namespace_uri_arg;

    char *endptr = NULL;
    long timeout_ms = strtol(timeout_arg, &endptr, 10);
    if(endptr == timeout_arg || timeout_ms <= 0) {
        fprintf(stderr, "invalid timeout_ms: %s\n", timeout_arg);
        return 2;
    }

    UA_Client *client = UA_Client_new();
    if(client == NULL) {
        fprintf(stderr, "failed to create client\n");
        return 1;
    }

    UA_ClientConfig *config = UA_Client_getConfig(client);
    UA_ClientConfig_setDefault(config);
    config->timeout = (UA_UInt32)timeout_ms;
    config->requestedSessionTimeout = (UA_UInt32)(timeout_ms * 2);

    UA_StatusCode connect_status = UA_Client_connect(client, endpoint);
    if(connect_status != UA_STATUSCODE_GOOD) {
        fprintf(stderr, "connect failed: %s\n", UA_StatusCode_name(connect_status));
        UA_Client_delete(client);
        return 1;
    }

    UA_UInt16 namespace_index = 0;
    if(namespace_uri != NULL && namespace_uri[0] != '\0') {
        UA_StatusCode ns_status = UA_Client_getNamespaceIndex(
            client,
            UA_STRING((char *)(uintptr_t)namespace_uri),
            &namespace_index
        );
        if(ns_status != UA_STATUSCODE_GOOD) {
            fprintf(stderr, "namespace lookup failed: %s\n", UA_StatusCode_name(ns_status));
            UA_Client_disconnect(client);
            UA_Client_delete(client);
            return 1;
        }
    }

    AppContext app = {
        .client = client,
        .namespace_index = namespace_index,
        .plans = NULL,
    };

    printf("READY\t%u\n", (unsigned)namespace_index);
    fflush(stdout);

    int exit_code = run_loop(&app);

    free_plans(app.plans);
    UA_Client_disconnect(client);
    UA_Client_delete(client);
    return exit_code;
}
