// Vulkan compute runner: creates instance, selects first compute-capable GPU,
// loads shader.spv from the same directory, creates compute pipeline, dispatches
// a compute workload writing to a device buffer, reads back data and prints
// JSON with timing information. Supports --enable-validation to activate the
// standard validation layer when available. Uses timestamp queries for GPU
// timing when supported. Provides signal-based cancellation.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <time.h>
#include <vulkan/vulkan.h>

// Note: This example focuses on being compact and educational. It omits
// detailed error handling and many production-quality checks. It assumes a
// Vulkan SDK and libvulkan are available at build and runtime.

static uint64_t now_ns() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static char* read_spv(const char* path, size_t* out_size) {
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    char* buf = malloc(sz);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, sz, f) != (size_t)sz) { free(buf); fclose(f); return NULL; }
    fclose(f);
    *out_size = sz;
    return buf;
}

#include <signal.h>

static volatile sig_atomic_t cancelled = 0;

static void handle_sig(int sig) {
    (void)sig;
    cancelled = 1;
}

// helper: check if a layer is available
static int layer_available(const char* name) {
    uint32_t count = 0;
    vkEnumerateInstanceLayerProperties(&count, NULL);
    if (count == 0) return 0;
    VkLayerProperties* props = malloc(sizeof(VkLayerProperties) * count);
    vkEnumerateInstanceLayerProperties(&count, props);
    int found = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (strcmp(props[i].layerName, name) == 0) { found = 1; break; }
    }
    free(props);
    return found;
}

// Debug callback for validation layers
static VKAPI_ATTR VkBool32 VKAPI_CALL debug_callback(
    VkDebugUtilsMessageSeverityFlagBitsEXT messageSeverity,
    VkDebugUtilsMessageTypeFlagsEXT messageType,
    const VkDebugUtilsMessengerCallbackDataEXT* pCallbackData,
    void* pUserData) {
    (void)messageSeverity; (void)messageType; (void)pUserData;
    fprintf(stderr, "[vulkan] %s\n", pCallbackData->pMessage);
    return VK_FALSE;
}

// Helpers to create/destroy debug messenger (if extension available)
static PFN_vkCreateDebugUtilsMessengerEXT pfnCreateDebugUtilsMessenger = NULL;
static PFN_vkDestroyDebugUtilsMessengerEXT pfnDestroyDebugUtilsMessenger = NULL;

static VkResult create_debug_messenger(VkInstance instance, VkDebugUtilsMessengerEXT* out) {
    pfnCreateDebugUtilsMessenger = (PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance, "vkCreateDebugUtilsMessengerEXT");
    if (!pfnCreateDebugUtilsMessenger) return VK_ERROR_EXTENSION_NOT_PRESENT;
    VkDebugUtilsMessengerCreateInfoEXT ci = { .sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT,
        .messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT,
        .messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT,
        .pfnUserCallback = debug_callback };
    return pfnCreateDebugUtilsMessenger(instance, &ci, NULL, out);
}

static void destroy_debug_messenger(VkInstance instance, VkDebugUtilsMessengerEXT messenger) {
    pfnDestroyDebugUtilsMessenger = (PFN_vkDestroyDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance, "vkDestroyDebugUtilsMessengerEXT");
    if (pfnDestroyDebugUtilsMessenger) pfnDestroyDebugUtilsMessenger(instance, messenger, NULL);
}

int main(int argc, char** argv) {
    const char* spv_path = "shader.spv";
    uint32_t count = 1024 * 64;
    uint32_t local_size = 64; // must match shader compiled local_size_x
    int enable_validation = 0;
    uint32_t iterations = 1;
    int do_health_check = 0;
    char protocol[32] = "ndjson";
    // simple arg parsing
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--count") == 0 && i + 1 < argc) { count = (uint32_t)atoi(argv[++i]); }
        else if (strcmp(argv[i], "--local-size") == 0 && i + 1 < argc) { local_size = (uint32_t)atoi(argv[++i]); }
        else if (strcmp(argv[i], "--enable-validation") == 0) { enable_validation = 1; }
        else if (strcmp(argv[i], "--shader") == 0 && i + 1 < argc) { spv_path = argv[++i]; }
        else if (strcmp(argv[i], "--iterations") == 0 && i + 1 < argc) { iterations = (uint32_t)atoi(argv[++i]); }
        else if (strcmp(argv[i], "--health-check") == 0) { do_health_check = 1; }
        else if (strcmp(argv[i], "--protocol") == 0 && i + 1 < argc) { strncpy(protocol, argv[++i], sizeof(protocol)-1); protocol[sizeof(protocol)-1] = '\0'; }
    }

    // install signal handlers for graceful cancellation
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sig;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    // Ensure count is multiple of local_size
    if (count % local_size) {
        count = ((count / local_size) + 1) * local_size;
    }

    // If validation requested but missing, print guidance
    if (enable_validation && !layer_available("VK_LAYER_KHRONOS_validation")) {
        fprintf(stderr, "{\"warning\": \"VK_LAYER_KHRONOS_validation not available. Install Vulkan SDK or validation layers to enable.\"}\n");
    }

    size_t spv_size = 0;
    char* spv = read_spv(spv_path, &spv_size);
    const char* spv_path = "shader.spv";
    uint32_t count = 1024 * 64;
    uint32_t local_size = 64; // must match shader compiled local_size_x
    int enable_validation = 0;
    // simple arg parsing
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--count") == 0 && i + 1 < argc) { count = (uint32_t)atoi(argv[++i]); }
        else if (strcmp(argv[i], "--local-size") == 0 && i + 1 < argc) { local_size = (uint32_t)atoi(argv[++i]); }
        else if (strcmp(argv[i], "--enable-validation") == 0) { enable_validation = 1; }
        else if (strcmp(argv[i], "--shader") == 0 && i + 1 < argc) { spv_path = argv[++i]; }
    }

    // install signal handlers for graceful cancellation
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sig;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    // Ensure count is multiple of local_size
    if (count % local_size) {
        count = ((count / local_size) + 1) * local_size;
    }

    // If validation requested, note (not enabling layers in this minimal runner)
    (void)enable_validation;

    size_t spv_size = 0;
    char* spv = read_spv(spv_path, &spv_size);
    size_t spv_size = 0;
    char* spv = read_spv(spv_path, &spv_size);
    if (!spv) {
        fprintf(stderr, "{\"error\": \"Failed to read shader.spv\"}\n");
        return 1;
    }

    VkResult r;
    VkInstance instance;
    const char* enabled_layers[1];
    const char* enabled_exts[1];
    uint32_t layer_count = 0, ext_count = 0;
    if (enable_validation && layer_available("VK_LAYER_KHRONOS_validation")) {
        enabled_layers[layer_count++] = "VK_LAYER_KHRONOS_validation";
        enabled_exts[ext_count++] = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
    }
    VkInstanceCreateInfo ici = { 0 };
    ici.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ici.enabledLayerCount = layer_count;
    ici.ppEnabledLayerNames = layer_count ? enabled_layers : NULL;
    ici.enabledExtensionCount = ext_count;
    ici.ppEnabledExtensionNames = ext_count ? enabled_exts : NULL;
    r = vkCreateInstance(&ici, NULL, &instance);
    if (r != VK_SUCCESS) {
        fprintf(stderr, "{\"error\": \"vkCreateInstance failed\", \"vk_result\": %d}\n", (int)r);
        free(spv);
        return 1;
    }

    // If health-check requested, enumerate devices and print JSON info then exit
    if (do_health_check) {
        uint32_t devcount = 0;
        vkEnumeratePhysicalDevices(instance, &devcount, NULL);
        if (devcount == 0) {
            fprintf(stdout, "[]\n");
            vkDestroyInstance(instance, NULL);
            free(spv);
            return 0;
        }
        VkPhysicalDevice* devs = malloc(sizeof(VkPhysicalDevice) * devcount);
        vkEnumeratePhysicalDevices(instance, &devcount, devs);
        printf("[");
        for (uint32_t i = 0; i < devcount; ++i) {
            VkPhysicalDeviceProperties p;
            vkGetPhysicalDeviceProperties(devs[i], &p);
            // Print minimal JSON per-device
            printf("{\"name\": \"%s\", \"vendorID\": %u, \"deviceID\": %u, \"apiVersion\": %u, \"timestampPeriod\": %.3f}", p.deviceName, p.vendorID, p.deviceID, p.apiVersion, p.limits.timestampPeriod);
            if (i + 1 < devcount) printf(",");
        }
        printf("]\n");
        free(devs);
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 0;
    }

    // helper to print framed messages according to protocol
    void print_msg(const char* proto, const char* jsonstr) {
        if (strcmp(proto, "netstring") == 0) {
            size_t len = strlen(jsonstr);
            // netstring: <len>:<json>,
            printf("%zu:%s,\n", len, jsonstr);
            fflush(stdout);
        } else {
            // default: ndjson (newline-delimited JSON)
            printf("%s\n", jsonstr);
            fflush(stdout);
        }
    }

    // If validation enabled and debug utils present, create messenger
    VkDebugUtilsMessengerEXT debug_messenger = VK_NULL_HANDLE;
    if (layer_count && ext_count) {
        if (create_debug_messenger(instance, &debug_messenger) != VK_SUCCESS) {
            fprintf(stderr, "{\"warning\": \"debug messenger not available\"}\n");
        }
    }

    uint32_t gpu_count = 0;
    vkEnumeratePhysicalDevices(instance, &gpu_count, NULL);
    if (gpu_count == 0) {
        fprintf(stderr, "{\"error\": \"No Vulkan physical devices\"}\n");
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 1;
    }
    VkPhysicalDevice* gpus = malloc(sizeof(VkPhysicalDevice) * gpu_count);
    vkEnumeratePhysicalDevices(instance, &gpu_count, gpus);

    // Pick first device with compute capability
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    uint32_t chosen_queue_family = UINT32_MAX;
    for (uint32_t i = 0; i < gpu_count; ++i) {
        VkPhysicalDevice dev = gpus[i];
        uint32_t qcount = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(dev, &qcount, NULL);
        VkQueueFamilyProperties* qprops = malloc(sizeof(VkQueueFamilyProperties) * qcount);
        vkGetPhysicalDeviceQueueFamilyProperties(dev, &qcount, qprops);
        for (uint32_t q = 0; q < qcount; ++q) {
            if (qprops[q].queueFlags & VK_QUEUE_COMPUTE_BIT) {
                physical = dev;
                chosen_queue_family = q;
                break;
            }
        }
        free(qprops);
        if (physical != VK_NULL_HANDLE) break;
    }
    if (physical == VK_NULL_HANDLE) {
        fprintf(stderr, "{\"error\": \"No compute-capable device\"}\n");
        free(gpus);
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 1;
    }

    float qprio = 1.0f;
    VkDeviceQueueCreateInfo dqci = { .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = chosen_queue_family, .queueCount = 1, .pQueuePriorities = &qprio };
    VkDeviceCreateInfo dci = { .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &dqci };
    VkDevice device;
    r = vkCreateDevice(physical, &dci, NULL, &device);
    if (r != VK_SUCCESS) {
        fprintf(stderr, "{\"error\": \"vkCreateDevice failed\"}\n");
        free(gpus);
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 1;
    }

    VkQueue queue;
    vkGetDeviceQueue(device, chosen_queue_family, 0, &queue);

    // Create shader module
    VkShaderModuleCreateInfo smci = { .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = spv_size, .pCode = (const uint32_t*)spv };
    VkShaderModule shader;
    r = vkCreateShaderModule(device, &smci, NULL, &shader);
    if (r != VK_SUCCESS) {
        fprintf(stderr, "{\"error\": \"vkCreateShaderModule failed\"}\n");
        vkDestroyDevice(device, NULL);
        free(gpus);
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 1;
    }

    // Create descriptor set layout for a storage buffer binding 0
    VkDescriptorSetLayoutBinding b = { .binding = 0, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT };
    VkDescriptorSetLayoutCreateInfo dslci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 1, .pBindings = &b };
    VkDescriptorSetLayout dsl;
    vkCreateDescriptorSetLayout(device, &dslci, NULL, &dsl);

    // Create pipeline layout
    VkPipelineLayoutCreateInfo plci = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &dsl };
    VkPipelineLayout pl;
    vkCreatePipelineLayout(device, &plci, NULL, &pl);

    // Create compute pipeline
    VkPipelineShaderStageCreateInfo pssci = { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = shader, .pName = "main" };
    VkComputePipelineCreateInfo cpci = { .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .stage = pssci, .layout = pl };
    VkPipeline pipeline;
    r = vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &cpci, NULL, &pipeline);
    if (r != VK_SUCCESS) {
        fprintf(stderr, "{\"error\": \"vkCreateComputePipelines failed\"}\n");
        vkDestroyPipelineLayout(device, pl, NULL);
        vkDestroyDescriptorSetLayout(device, dsl, NULL);
        vkDestroyShaderModule(device, shader, NULL);
        vkDestroyDevice(device, NULL);
        free(gpus);
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 1;
    }

    // Create buffer for results
    const uint32_t count = 1024 * 64; // number of uints to write
    VkDeviceSize buf_size = sizeof(uint32_t) * count;
    VkBufferCreateInfo bci = { .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = buf_size, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE };
    VkBuffer buf;
    vkCreateBuffer(device, &bci, NULL, &buf);

    VkMemoryRequirements memreq;
    vkGetBufferMemoryRequirements(device, buf, &memreq);

    // find memory type with host visible bit
    VkPhysicalDeviceMemoryProperties memprops;
    vkGetPhysicalDeviceMemoryProperties(physical, &memprops);
    uint32_t memtype = UINT32_MAX;
    for (uint32_t i = 0; i < memprops.memoryTypeCount; ++i) {
        if ((memreq.memoryTypeBits & (1u << i)) && (memprops.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)) {
            memtype = i; break;
        }
    }
    if (memtype == UINT32_MAX) {
        fprintf(stderr, "{\"error\": \"No host visible memory type\"}\n");
        vkDestroyPipeline(device, pipeline, NULL);
        vkDestroyPipelineLayout(device, pl, NULL);
        vkDestroyDescriptorSetLayout(device, dsl, NULL);
        vkDestroyShaderModule(device, shader, NULL);
        vkDestroyDevice(device, NULL);
        free(gpus);
        vkDestroyInstance(instance, NULL);
        free(spv);
        return 1;
    }

    VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = memreq.size, .memoryTypeIndex = memtype };
    VkDeviceMemory mem;
    vkAllocateMemory(device, &mai, NULL, &mem);
    vkBindBufferMemory(device, buf, mem, 0);

    // Descriptor pool & set
    VkDescriptorPoolSize dps = { .type = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount = 1 };
    VkDescriptorPoolCreateInfo dpci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &dps };
    VkDescriptorPool dpool;
    vkCreateDescriptorPool(device, &dpci, NULL, &dpool);

    VkDescriptorSetAllocateInfo dsai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = dpool, .descriptorSetCount = 1, .pSetLayouts = &dsl };
    VkDescriptorSet dset;
    vkAllocateDescriptorSets(device, &dsai, &dset);

    VkDescriptorBufferInfo dbi = { .buffer = buf, .offset = 0, .range = buf_size };
    VkWriteDescriptorSet wds = { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = dset, .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &dbi };
    vkUpdateDescriptorSets(device, 1, &wds, 0, NULL);

    // Create command pool and buffer
    VkCommandPoolCreateInfo cpci_cmd = { .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = chosen_queue_family };
    VkCommandPool cmdpool;
    vkCreateCommandPool(device, &cpci_cmd, NULL, &cmdpool);

    VkCommandBufferAllocateInfo cbai = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cmdpool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1 };
    VkCommandBuffer cmdbuf;
    vkAllocateCommandBuffers(device, &cbai, &cmdbuf);
    // Create query pool for timestamp (if supported)
    VkQueryPool queryPool = VK_NULL_HANDLE;
    VkPhysicalDeviceProperties pdprops;
    vkGetPhysicalDeviceProperties(physical, &pdprops);
    int have_timestamps = 1; // assume available; not all devices may support
    VkQueryPoolCreateInfo qpci = { .sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO, .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 2 };
    if (vkCreateQueryPool(device, &qpci, NULL, &queryPool) != VK_SUCCESS) {
        queryPool = VK_NULL_HANDLE;
        have_timestamps = 0;
    }

    // Record commands: bind pipeline and dispatch (we will record once and re-submit per iteration)
    VkCommandBufferBeginInfo cbbi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
    vkBeginCommandBuffer(cmdbuf, &cbbi);
    if (queryPool != VK_NULL_HANDLE) vkCmdResetQueryPool(cmdbuf, queryPool, 0, 2);
    if (queryPool != VK_NULL_HANDLE) vkCmdWriteTimestamp(cmdbuf, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, queryPool, 0);
    vkCmdBindPipeline(cmdbuf, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(cmdbuf, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &dset, 0, NULL);
    // dispatch enough workgroups to cover 'count' items (local_size_x variable)
    uint32_t group_count = (count + (local_size - 1)) / local_size;
    vkCmdDispatch(cmdbuf, group_count, 1, 1);
    if (queryPool != VK_NULL_HANDLE) vkCmdWriteTimestamp(cmdbuf, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, queryPool, 1);
    vkEndCommandBuffer(cmdbuf);

    VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
    VkFence fence;
    vkCreateFence(device, &fci, NULL, &fence);

    // We will submit the recorded command buffer 'iterations' times and optionally print progress after each.
    double total_cpu_time = 0.0;
    double total_items_per_s = 0.0;
    for (uint32_t iter = 0; iter < iterations; ++iter) {
        if (cancelled) break;
        uint64_t t0 = now_ns();
        VkSubmitInfo si = { .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cmdbuf };
        vkQueueSubmit(queue, 1, &si, fence);
        // Wait for fence with cancellable loop
        uint64_t t1 = t0;
        while (!cancelled) {
            VkResult wr = vkWaitForFences(device, 1, &fence, VK_TRUE, 100000000); // 100ms
            if (wr == VK_SUCCESS) {
                t1 = now_ns();
                break;
            }
            if (wr != VK_TIMEOUT) { t1 = now_ns(); break; }
        }
        double elapsed_s = (t1 - t0) / 1e9;
        double items_per_s = (double)count / (elapsed_s > 0 ? elapsed_s : 1e-9);
        total_cpu_time += elapsed_s;
        total_items_per_s += items_per_s;
        // Read back first value to validate
        void* ptr_iter = NULL;
        vkMapMemory(device, mem, 0, sizeof(uint32_t), 0, &ptr_iter);
        uint32_t sample_iter = *((uint32_t*)ptr_iter);
        vkUnmapMemory(device, mem);
        // Print a progress JSON line for the iteration
        {
            char buf[512];
            int n = snprintf(buf, sizeof(buf), "{\"progress\": {\"iter\": %u, \"total\": %u, \"cpu_time_s\": %.9f, \"items_per_s\": %.2f, \"sample0\": %u}}", iter+1, iterations, elapsed_s, items_per_s, sample_iter);
            if (n > 0) print_msg(protocol, buf);
        }
        // reset fence for next iteration
        vkResetFences(device, 1, &fence);
        // small yield
    }
    if (cancelled) {
        fprintf(stderr, "{\"cancelled\": true}\n");
    }

    // Map and read back first few entries to validate
    void* ptr = NULL;
    vkMapMemory(device, mem, 0, buf_size, 0, &ptr);
    uint32_t* data = (uint32_t*)ptr;
    uint32_t sample0 = data[0];
    vkUnmapMemory(device, mem);

    // Read timestamp results if available
    double gpu_time_s = 0.0;
    if (queryPool != VK_NULL_HANDLE) {
        uint64_t timestamps[2] = {0,0};
        VkResult qr = vkGetQueryPoolResults(device, queryPool, 0, 2, sizeof(timestamps), timestamps, sizeof(uint64_t), VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
        if (qr == VK_SUCCESS) {
            // convert ticks to seconds using timestampPeriod
            double period_ns = pdprops.limits.timestampPeriod; // in nanoseconds
            uint64_t diff = timestamps[1] - timestamps[0];
            gpu_time_s = (diff * period_ns) / 1e9;
        }
    }

    double elapsed_s = (t1 - t0) / 1e9;
    double items_per_s = (double)count / (elapsed_s > 0 ? elapsed_s : 1e-9);

    // Print JSON result including GPU timestamp if present
    if (gpu_time_s > 0.0) {
        char buf[256];
        int n = snprintf(buf, sizeof(buf), "{\"count\": %u, \"cpu_time_s\": %.9f, \"gpu_time_s\": %.9f, \"items_per_s\": %.2f, \"sample0\": %u}", count, elapsed_s, gpu_time_s, items_per_s, sample0);
        if (n > 0) print_msg(protocol, buf);
    } else {
        char buf[256];
        int n = snprintf(buf, sizeof(buf), "{\"count\": %u, \"cpu_time_s\": %.9f, \"items_per_s\": %.2f, \"sample0\": %u}", count, elapsed_s, items_per_s, sample0);
        if (n > 0) print_msg(protocol, buf);
    }

    // cleanup
    vkDestroyFence(device, fence, NULL);
    vkFreeCommandBuffers(device, cmdpool, 1, &cmdbuf);
    vkDestroyCommandPool(device, cmdpool, NULL);
    vkDestroyDescriptorPool(device, dpool, NULL);
    if (queryPool != VK_NULL_HANDLE) vkDestroyQueryPool(device, queryPool, NULL);
    vkFreeMemory(device, mem, NULL);
    vkDestroyBuffer(device, buf, NULL);
    vkDestroyPipeline(device, pipeline, NULL);
    vkDestroyPipelineLayout(device, pl, NULL);
    vkDestroyDescriptorSetLayout(device, dsl, NULL);
    vkDestroyShaderModule(device, shader, NULL);
    if (debug_messenger != VK_NULL_HANDLE) destroy_debug_messenger(instance, debug_messenger);
    vkDestroyDevice(device, NULL);
    vkDestroyInstance(instance, NULL);
    free(gpus);
    free(spv);
    return 0;
}

