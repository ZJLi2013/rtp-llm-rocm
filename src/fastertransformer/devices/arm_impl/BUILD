load("//:def.bzl", "copts")

cc_library(
    name = "arm_cpu_impl",
    hdrs = glob([
        "*.h",
    ]),
    srcs = glob([
        "*.cc",
    ]),
    deps = [
        "//src/fastertransformer/devices:devices_base",
        "//src/fastertransformer/devices:devices_base_impl",
        "//src/fastertransformer/core:cpu_allocator",
    ],
    visibility = ["//visibility:public"],
    copts = copts(),
)
