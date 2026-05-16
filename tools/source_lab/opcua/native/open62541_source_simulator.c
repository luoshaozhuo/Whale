#define _POSIX_C_SOURCE 200809L

#include <open62541/plugin/log_stdout.h>
#include <open62541/server.h>
#include <open62541/server_config_default.h>

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>

#define MAX_LINE_LEN 8192

typedef struct NodeConfig {
    char *node_id;
    char *browse_name;
    char *display_name;
    char *data_type;
    char *initial_value;
    unsigned long update_counter;
    struct NodeConfig *next;
} NodeConfig;

typedef struct AppConfig {
    char *endpoint;
    char *namespace_uri;
    bool update_enabled;
    unsigned long update_interval_ms;
    bool update_all;
    NodeConfig *nodes;
} AppConfig;

typedef struct StringSetItem {
    char *value;
    struct StringSetItem *next;
} StringSetItem;

static volatile UA_Boolean running = true;

static void stop_handler(int sig) {
    (void)sig;
    running = false;
}

static char *xstrdup(const char *value) {
    size_t len = strlen(value);
    char *copy = (char *)malloc(len + 1);
    if (copy == NULL) {
        return NULL;
    }
    memcpy(copy, value, len + 1);
    return copy;
}

static bool parse_bool(const char *value) {
    if (value == NULL) {
        return false;
    }

    return strcmp(value, "1") == 0 ||
           strcmp(value, "true") == 0 ||
           strcmp(value, "TRUE") == 0 ||
           strcmp(value, "yes") == 0 ||
           strcmp(value, "YES") == 0 ||
           strcmp(value, "on") == 0 ||
           strcmp(value, "ON") == 0;
}

static void strip_newline(char *line) {
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
        line[len - 1] = '\0';
        len--;
    }
}

static bool split_fields(char *line, char **fields, int max_fields, int *field_count) {
    int count = 0;
    char *cursor = line;

    while (cursor != NULL && count < max_fields) {
        fields[count++] = cursor;

        char *tab = strchr(cursor, '\t');
        if (tab == NULL) {
            break;
        }

        *tab = '\0';
        cursor = tab + 1;
    }

    *field_count = count;
    return true;
}

static void free_config(AppConfig *config) {
    if (config == NULL) {
        return;
    }

    free(config->endpoint);
    free(config->namespace_uri);

    NodeConfig *node = config->nodes;
    while (node != NULL) {
        NodeConfig *next = node->next;
        free(node->node_id);
        free(node->browse_name);
        free(node->display_name);
        free(node->data_type);
        free(node->initial_value);
        free(node);
        node = next;
    }

    config->endpoint = NULL;
    config->namespace_uri = NULL;
    config->nodes = NULL;
}

static bool append_node_config(AppConfig *config, char **fields, int field_count) {
    if (field_count != 6) {
        fprintf(stderr, "Invalid node line: expected 6 fields, got %d\n", field_count);
        return false;
    }

    if (
        strcmp(fields[4], "Double") != 0 &&
        strcmp(fields[4], "Int32") != 0 &&
        strcmp(fields[4], "Boolean") != 0 &&
        strcmp(fields[4], "String") != 0
    ) {
        fprintf(stderr, "Unsupported node data_type in config: %s\n", fields[4]);
        return false;
    }

    NodeConfig *node = (NodeConfig *)calloc(1, sizeof(NodeConfig));
    if (node == NULL) {
        return false;
    }

    node->node_id = xstrdup(fields[1]);
    node->browse_name = xstrdup(fields[2]);
    node->display_name = xstrdup(fields[3]);
    node->data_type = xstrdup(fields[4]);
    node->initial_value = xstrdup(fields[5]);
    node->update_counter = 0;

    if (
        node->node_id == NULL ||
        node->browse_name == NULL ||
        node->display_name == NULL ||
        node->data_type == NULL ||
        node->initial_value == NULL
    ) {
        free(node->node_id);
        free(node->browse_name);
        free(node->display_name);
        free(node->data_type);
        free(node->initial_value);
        free(node);
        return false;
    }

    node->next = config->nodes;
    config->nodes = node;
    return true;
}

static bool load_config(const char *path, AppConfig *config) {
    config->update_enabled = false;
    config->update_interval_ms = 1000;
    config->update_all = true;

    FILE *fp = fopen(path, "r");
    if (fp == NULL) {
        perror("Failed to open config file");
        return false;
    }

    char line[MAX_LINE_LEN];

    while (fgets(line, sizeof(line), fp) != NULL) {
        strip_newline(line);

        if (line[0] == '\0' || line[0] == '#') {
            continue;
        }

        char *fields[8] = {0};
        int field_count = 0;
        split_fields(line, fields, 8, &field_count);

        if (field_count <= 0) {
            continue;
        }

        if (strcmp(fields[0], "endpoint") == 0) {
            if (field_count != 2) {
                fprintf(stderr, "Invalid endpoint line\n");
                fclose(fp);
                return false;
            }
            config->endpoint = xstrdup(fields[1]);
        } else if (strcmp(fields[0], "namespace_uri") == 0) {
            if (field_count != 2) {
                fprintf(stderr, "Invalid namespace_uri line\n");
                fclose(fp);
                return false;
            }
            config->namespace_uri = xstrdup(fields[1]);
        } else if (strcmp(fields[0], "update_enabled") == 0) {
            if (field_count != 2) {
                fprintf(stderr, "Invalid update_enabled line\n");
                fclose(fp);
                return false;
            }
            config->update_enabled = parse_bool(fields[1]);
        } else if (strcmp(fields[0], "update_interval_ms") == 0) {
            if (field_count != 2) {
                fprintf(stderr, "Invalid update_interval_ms line\n");
                fclose(fp);
                return false;
            }
            long interval = strtol(fields[1], NULL, 10);
            config->update_interval_ms = interval > 0 ? (unsigned long)interval : 1000;
        } else if (strcmp(fields[0], "update_all") == 0) {
            if (field_count != 2) {
                fprintf(stderr, "Invalid update_all line\n");
                fclose(fp);
                return false;
            }
            config->update_all = parse_bool(fields[1]);
        } else if (strcmp(fields[0], "node") == 0) {
            if (!append_node_config(config, fields, field_count)) {
                fclose(fp);
                return false;
            }
        } else {
            fprintf(stderr, "Unknown TSV record type: %s\n", fields[0]);
            fclose(fp);
            return false;
        }
    }

    fclose(fp);

    if (config->endpoint == NULL || config->namespace_uri == NULL) {
        fprintf(stderr, "Config requires endpoint and namespace_uri\n");
        return false;
    }

    if (config->nodes == NULL) {
        fprintf(stderr, "Config requires at least one node\n");
        return false;
    }

    return true;
}

static unsigned short parse_endpoint_port(const char *endpoint) {
    const char *colon = strrchr(endpoint, ':');
    if (colon == NULL || *(colon + 1) == '\0') {
        return 4840;
    }

    long port = strtol(colon + 1, NULL, 10);
    if (port <= 0 || port > 65535) {
        return 4840;
    }

    return (unsigned short)port;
}

static bool string_set_contains(StringSetItem *head, const char *value) {
    for (StringSetItem *item = head; item != NULL; item = item->next) {
        if (strcmp(item->value, value) == 0) {
            return true;
        }
    }
    return false;
}

static bool string_set_add(StringSetItem **head, const char *value) {
    if (string_set_contains(*head, value)) {
        return true;
    }

    StringSetItem *item = (StringSetItem *)calloc(1, sizeof(StringSetItem));
    if (item == NULL) {
        return false;
    }

    item->value = xstrdup(value);
    if (item->value == NULL) {
        free(item);
        return false;
    }

    item->next = *head;
    *head = item;
    return true;
}

static void free_string_set(StringSetItem *head) {
    while (head != NULL) {
        StringSetItem *next = head->next;
        free(head->value);
        free(head);
        head = next;
    }
}

static char *join_parts(char **parts, int count) {
    size_t len = 0;

    for (int i = 0; i < count; i++) {
        len += strlen(parts[i]);
        if (i > 0) {
            len += 1;
        }
    }

    char *result = (char *)calloc(len + 1, sizeof(char));
    if (result == NULL) {
        return NULL;
    }

    for (int i = 0; i < count; i++) {
        if (i > 0) {
            strcat(result, ".");
        }
        strcat(result, parts[i]);
    }

    return result;
}

static int split_node_id_parts(const char *node_id, char **parts, int max_parts) {
    char *copy = xstrdup(node_id);
    if (copy == NULL) {
        return 0;
    }

    int count = 0;
    char *cursor = copy;

    while (cursor != NULL && count < max_parts) {
        parts[count++] = cursor;

        char *dot = strchr(cursor, '.');
        if (dot == NULL) {
            break;
        }

        *dot = '\0';
        cursor = dot + 1;
    }

    for (int i = 0; i < count; i++) {
        parts[i] = xstrdup(parts[i]);
    }

    free(copy);

    for (int i = 0; i < count; i++) {
        if (parts[i] == NULL) {
            for (int j = 0; j < i; j++) {
                free(parts[j]);
            }
            return 0;
        }
    }

    return count;
}

static void free_parts(char **parts, int count) {
    for (int i = 0; i < count; i++) {
        free(parts[i]);
    }
}

static char *parent_path_from_node_id(const char *node_id) {
    const char *last_dot = strrchr(node_id, '.');
    if (last_dot == NULL || last_dot == node_id) {
        return NULL;
    }

    size_t len = (size_t)(last_dot - node_id);
    char *parent = (char *)calloc(len + 1, sizeof(char));
    if (parent == NULL) {
        return NULL;
    }

    memcpy(parent, node_id, len);
    parent[len] = '\0';
    return parent;
}

static UA_StatusCode add_object_node(
    UA_Server *server,
    UA_UInt16 ns_idx,
    const char *node_id,
    const char *browse_name,
    const char *display_name,
    const char *parent_node_id,
    bool parent_is_objects_folder,
    bool use_organizes_ref
) {
    UA_ObjectAttributes attr = UA_ObjectAttributes_default;
    attr.displayName = UA_LOCALIZEDTEXT_ALLOC("en-US", display_name);

    UA_NodeId requested = UA_NODEID_STRING_ALLOC(ns_idx, node_id);
    UA_QualifiedName qn = UA_QUALIFIEDNAME_ALLOC(ns_idx, browse_name);

    UA_NodeId parent;
    if (parent_is_objects_folder) {
        parent = UA_NODEID_NUMERIC(0, UA_NS0ID_OBJECTSFOLDER);
    } else {
        parent = UA_NODEID_STRING_ALLOC(ns_idx, parent_node_id);
    }

    UA_NodeId ref = use_organizes_ref
        ? UA_NODEID_NUMERIC(0, UA_NS0ID_ORGANIZES)
        : UA_NODEID_NUMERIC(0, UA_NS0ID_HASCOMPONENT);

    UA_NodeId type_definition = use_organizes_ref
        ? UA_NODEID_NUMERIC(0, UA_NS0ID_FOLDERTYPE)
        : UA_NODEID_NUMERIC(0, UA_NS0ID_BASEOBJECTTYPE);

    UA_StatusCode status = UA_Server_addObjectNode(
        server,
        requested,
        parent,
        ref,
        qn,
        type_definition,
        attr,
        NULL,
        NULL
    );

    UA_ObjectAttributes_clear(&attr);
    UA_NodeId_clear(&requested);
    UA_QualifiedName_clear(&qn);

    if (!parent_is_objects_folder) {
        UA_NodeId_clear(&parent);
    }

    return status;
}

static UA_StatusCode build_variant_from_text(
    UA_Variant *variant,
    UA_NodeId *data_type,
    const char *type_name,
    const char *value
) {
    UA_Variant_init(variant);

    if (strcmp(type_name, "Double") == 0) {
        UA_Double parsed = strtod(value, NULL);
        *data_type = UA_TYPES[UA_TYPES_DOUBLE].typeId;
        return UA_Variant_setScalarCopy(variant, &parsed, &UA_TYPES[UA_TYPES_DOUBLE]);
    }

    if (strcmp(type_name, "Int32") == 0) {
        UA_Int32 parsed = (UA_Int32)strtol(value, NULL, 10);
        *data_type = UA_TYPES[UA_TYPES_INT32].typeId;
        return UA_Variant_setScalarCopy(variant, &parsed, &UA_TYPES[UA_TYPES_INT32]);
    }

    if (strcmp(type_name, "Boolean") == 0) {
        UA_Boolean parsed = parse_bool(value);
        *data_type = UA_TYPES[UA_TYPES_BOOLEAN].typeId;
        return UA_Variant_setScalarCopy(variant, &parsed, &UA_TYPES[UA_TYPES_BOOLEAN]);
    }

    if (strcmp(type_name, "String") == 0) {
        UA_String parsed = UA_STRING((char *)value);
        *data_type = UA_TYPES[UA_TYPES_STRING].typeId;
        return UA_Variant_setScalarCopy(variant, &parsed, &UA_TYPES[UA_TYPES_STRING]);
    }

    return UA_STATUSCODE_BADTYPEMISMATCH;
}

static UA_StatusCode write_node_value(
    UA_Server *server,
    UA_UInt16 ns_idx,
    const char *node_id,
    const char *data_type,
    const char *value
) {
    UA_NodeId target = UA_NODEID_STRING_ALLOC(ns_idx, node_id);

    UA_Variant variant;
    UA_NodeId type_id = UA_NODEID_NULL;
    UA_StatusCode status = build_variant_from_text(&variant, &type_id, data_type, value);
    if (status != UA_STATUSCODE_GOOD) {
        UA_NodeId_clear(&target);
        fprintf(stderr, "Failed to build variant for %s type=%s value=%s: 0x%08x\n",
                node_id, data_type, value, status);
        return status;
    }

    UA_DateTime now = UA_DateTime_now();

    UA_DataValue data_value;
    UA_DataValue_init(&data_value);
    data_value.hasValue = true;
    data_value.value = variant;
    data_value.hasStatus = true;
    data_value.status = UA_STATUSCODE_GOOD;
    data_value.hasSourceTimestamp = true;
    data_value.sourceTimestamp = now;

    status = UA_Server_writeDataValue(server, target, data_value);

    UA_DataValue_clear(&data_value);
    UA_NodeId_clear(&target);

    if (status != UA_STATUSCODE_GOOD) {
        fprintf(stderr, "Failed to write node %s: 0x%08x\n", node_id, status);
    }

    return status;
}

static UA_StatusCode add_variable_node(
    UA_Server *server,
    UA_UInt16 ns_idx,
    const NodeConfig *node
) {
    char *parent_path = parent_path_from_node_id(node->node_id);
    if (parent_path == NULL) {
        fprintf(stderr, "Invalid variable node_id, cannot build parent path: %s\n", node->node_id);
        return UA_STATUSCODE_BADNODEIDINVALID;
    }

    UA_VariableAttributes attr = UA_VariableAttributes_default;
    attr.displayName = UA_LOCALIZEDTEXT_ALLOC("en-US", node->display_name);
    attr.accessLevel = UA_ACCESSLEVELMASK_READ | UA_ACCESSLEVELMASK_WRITE;
    attr.userAccessLevel = UA_ACCESSLEVELMASK_READ | UA_ACCESSLEVELMASK_WRITE;

    UA_NodeId data_type = UA_NODEID_NULL;
    UA_StatusCode status = build_variant_from_text(
        &attr.value,
        &data_type,
        node->data_type,
        node->initial_value
    );
    if (status != UA_STATUSCODE_GOOD) {
        free(parent_path);
        UA_VariableAttributes_clear(&attr);
        return status;
    }
    attr.dataType = data_type;

    UA_NodeId requested = UA_NODEID_STRING_ALLOC(ns_idx, node->node_id);
    UA_NodeId parent = UA_NODEID_STRING_ALLOC(ns_idx, parent_path);
    UA_QualifiedName qn = UA_QUALIFIEDNAME_ALLOC(ns_idx, node->browse_name);

    status = UA_Server_addVariableNode(
        server,
        requested,
        parent,
        UA_NODEID_NUMERIC(0, UA_NS0ID_HASCOMPONENT),
        qn,
        UA_NODEID_NUMERIC(0, UA_NS0ID_BASEDATAVARIABLETYPE),
        attr,
        NULL,
        NULL
    );

    if (status == UA_STATUSCODE_GOOD) {
        status = write_node_value(
            server,
            ns_idx,
            node->node_id,
            node->data_type,
            node->initial_value
        );
    }

    UA_NodeId_clear(&requested);
    UA_NodeId_clear(&parent);
    UA_QualifiedName_clear(&qn);
    UA_VariableAttributes_clear(&attr);
    free(parent_path);

    return status;
}

static bool ensure_object_hierarchy(
    UA_Server *server,
    UA_UInt16 ns_idx,
    const char *variable_node_id,
    StringSetItem **created_objects
) {
    if (!string_set_contains(*created_objects, "WindFarm")) {
        UA_StatusCode status = add_object_node(
            server,
            ns_idx,
            "WindFarm",
            "WindFarm",
            "WindFarm",
            NULL,
            true,
            true
        );
        if (status != UA_STATUSCODE_GOOD) {
            fprintf(stderr, "Failed to add WindFarm object: 0x%08x\n", status);
            return false;
        }
        string_set_add(created_objects, "WindFarm");
    }

    char *parts[8] = {0};
    int count = split_node_id_parts(variable_node_id, parts, 8);
    if (count < 4) {
        fprintf(stderr, "Invalid logical node_id: %s\n", variable_node_id);
        free_parts(parts, count);
        return false;
    }

    char *ied = join_parts(parts, 1);
    char *ld = join_parts(parts, 2);
    char *ln = join_parts(parts, 3);

    if (ied == NULL || ld == NULL || ln == NULL) {
        free(ied);
        free(ld);
        free(ln);
        free_parts(parts, count);
        return false;
    }

    if (!string_set_contains(*created_objects, ied)) {
        UA_StatusCode status = add_object_node(
            server,
            ns_idx,
            ied,
            parts[0],
            parts[0],
            "WindFarm",
            false,
            false
        );
        if (status != UA_STATUSCODE_GOOD) {
            fprintf(stderr, "Failed to add IED object %s: 0x%08x\n", ied, status);
            free(ied);
            free(ld);
            free(ln);
            free_parts(parts, count);
            return false;
        }
        string_set_add(created_objects, ied);
    }

    if (!string_set_contains(*created_objects, ld)) {
        UA_StatusCode status = add_object_node(
            server,
            ns_idx,
            ld,
            parts[1],
            parts[1],
            ied,
            false,
            false
        );
        if (status != UA_STATUSCODE_GOOD) {
            fprintf(stderr, "Failed to add LD object %s: 0x%08x\n", ld, status);
            free(ied);
            free(ld);
            free(ln);
            free_parts(parts, count);
            return false;
        }
        string_set_add(created_objects, ld);
    }

    if (!string_set_contains(*created_objects, ln)) {
        UA_StatusCode status = add_object_node(
            server,
            ns_idx,
            ln,
            parts[2],
            parts[2],
            ld,
            false,
            false
        );
        if (status != UA_STATUSCODE_GOOD) {
            fprintf(stderr, "Failed to add LN object %s: 0x%08x\n", ln, status);
            free(ied);
            free(ld);
            free(ln);
            free_parts(parts, count);
            return false;
        }
        string_set_add(created_objects, ln);
    }

    free(ied);
    free(ld);
    free(ln);
    free_parts(parts, count);
    return true;
}

static bool build_address_space(UA_Server *server, UA_UInt16 ns_idx, AppConfig *config) {
    StringSetItem *created_objects = NULL;

    for (NodeConfig *node = config->nodes; node != NULL; node = node->next) {
        if (!ensure_object_hierarchy(server, ns_idx, node->node_id, &created_objects)) {
            free_string_set(created_objects);
            return false;
        }
    }

    for (NodeConfig *node = config->nodes; node != NULL; node = node->next) {
        UA_StatusCode status = add_variable_node(server, ns_idx, node);
        if (status != UA_STATUSCODE_GOOD) {
            fprintf(stderr, "Failed to add variable %s: 0x%08x\n", node->node_id, status);
            free_string_set(created_objects);
            return false;
        }
    }

    free_string_set(created_objects);
    return true;
}

static int set_stdin_nonblocking(void) {
    int flags = fcntl(STDIN_FILENO, F_GETFL, 0);
    if (flags == -1) {
        return -1;
    }

    return fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK);
}

static bool stdin_has_data(void) {
    fd_set read_fds;
    FD_ZERO(&read_fds);
    FD_SET(STDIN_FILENO, &read_fds);

    struct timeval timeout;
    timeout.tv_sec = 0;
    timeout.tv_usec = 0;

    int result = select(STDIN_FILENO + 1, &read_fds, NULL, NULL, &timeout);
    return result > 0 && FD_ISSET(STDIN_FILENO, &read_fds);
}

static void process_write_command(
    UA_Server *server,
    UA_UInt16 ns_idx,
    char **fields,
    int field_count
) {
    if (field_count != 4) {
        fprintf(stderr, "Invalid write command: expected 4 fields, got %d\n", field_count);
        return;
    }

    const char *node_id = fields[1];
    const char *data_type = fields[2];
    const char *value = fields[3];

    if (
        strcmp(data_type, "Double") != 0 &&
        strcmp(data_type, "Int32") != 0 &&
        strcmp(data_type, "Boolean") != 0 &&
        strcmp(data_type, "String") != 0
    ) {
        fprintf(stderr, "Unsupported write data_type: %s\n", data_type);
        return;
    }

    (void)write_node_value(server, ns_idx, node_id, data_type, value);
}

static void process_stdin_commands(UA_Server *server, UA_UInt16 ns_idx) {
    if (!stdin_has_data()) {
        return;
    }

    char line[MAX_LINE_LEN];

    while (fgets(line, sizeof(line), stdin) != NULL) {
        strip_newline(line);

        if (line[0] == '\0') {
            continue;
        }

        char *fields[8] = {0};
        int field_count = 0;
        split_fields(line, fields, 8, &field_count);

        if (field_count <= 0) {
            continue;
        }

        if (strcmp(fields[0], "write") == 0) {
            process_write_command(server, ns_idx, fields, field_count);
        } else {
            fprintf(stderr, "Unknown stdin command: %s\n", fields[0]);
        }
    }

    if (ferror(stdin)) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            clearerr(stdin);
        } else {
            perror("stdin read failed");
            clearerr(stdin);
        }
    }

    if (feof(stdin)) {
        clearerr(stdin);
    }
}

static unsigned long monotonic_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);

    return ((unsigned long)ts.tv_sec * 1000UL) + ((unsigned long)ts.tv_nsec / 1000000UL);
}

static void build_internal_update_value(
    NodeConfig *node,
    char *buffer,
    size_t buffer_size
) {
    node->update_counter++;

    if (strcmp(node->data_type, "Double") == 0) {
        snprintf(buffer, buffer_size, "%.3f", (double)node->update_counter);
        return;
    }

    if (strcmp(node->data_type, "Int32") == 0) {
        snprintf(buffer, buffer_size, "%lu", node->update_counter % 100000UL);
        return;
    }

    if (strcmp(node->data_type, "Boolean") == 0) {
        snprintf(buffer, buffer_size, "%s", (node->update_counter % 2UL) == 0 ? "false" : "true");
        return;
    }

    if (strcmp(node->data_type, "String") == 0) {
        snprintf(buffer, buffer_size, "value_%lu", node->update_counter);
        return;
    }

    snprintf(buffer, buffer_size, "0");
}

static void maybe_run_internal_update(
    UA_Server *server,
    UA_UInt16 ns_idx,
    AppConfig *config,
    unsigned long *last_update_ms
) {
    if (!config->update_enabled) {
        return;
    }

    unsigned long now = monotonic_ms();
    if (*last_update_ms != 0 && now - *last_update_ms < config->update_interval_ms) {
        return;
    }

    *last_update_ms = now;

    int updated_count = 0;
    char value_buffer[256];

    for (NodeConfig *node = config->nodes; node != NULL; node = node->next) {
        build_internal_update_value(node, value_buffer, sizeof(value_buffer));
        (void)write_node_value(server, ns_idx, node->node_id, node->data_type, value_buffer);

        updated_count++;

        if (!config->update_all && updated_count >= 1) {
            break;
        }
    }
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <config.tsv>\n", argv[0]);
        return EXIT_FAILURE;
    }

    signal(SIGINT, stop_handler);
    signal(SIGTERM, stop_handler);

    AppConfig app_config = {0};

    if (!load_config(argv[1], &app_config)) {
        free_config(&app_config);
        return EXIT_FAILURE;
    }

    unsigned short port = parse_endpoint_port(app_config.endpoint);

    UA_Server *server = UA_Server_new();
    UA_ServerConfig *server_config = UA_Server_getConfig(server);

    UA_StatusCode status = UA_ServerConfig_setMinimal(server_config, port, NULL);
    if (status != UA_STATUSCODE_GOOD) {
        fprintf(stderr, "Failed to configure server: 0x%08x\n", status);
        UA_Server_delete(server);
        free_config(&app_config);
        return EXIT_FAILURE;
    }

    UA_UInt16 ns_idx = UA_Server_addNamespace(server, app_config.namespace_uri);

    if (!build_address_space(server, ns_idx, &app_config)) {
        UA_Server_delete(server);
        free_config(&app_config);
        return EXIT_FAILURE;
    }

    if (set_stdin_nonblocking() != 0) {
        perror("Failed to set stdin nonblocking");
    }

    status = UA_Server_run_startup(server);
    if (status != UA_STATUSCODE_GOOD) {
        fprintf(stderr, "Failed to start server: 0x%08x\n", status);
        UA_Server_delete(server);
        free_config(&app_config);
        return EXIT_FAILURE;
    }

    printf("READY\n");
    fflush(stdout);

    unsigned long last_update_ms = 0;

    while (running) {
        UA_Server_run_iterate(server, false);
        process_stdin_commands(server, ns_idx);
        maybe_run_internal_update(server, ns_idx, &app_config, &last_update_ms);
        usleep(1000);
    }

    status = UA_Server_run_shutdown(server);

    UA_Server_delete(server);
    free_config(&app_config);

    return status == UA_STATUSCODE_GOOD ? EXIT_SUCCESS : EXIT_FAILURE;
}
