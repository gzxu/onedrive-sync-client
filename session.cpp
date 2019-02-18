#include <memory>

#include <webkit2/webkit-web-extension.h>

#include "download.h"
#include "fetch.h"
#include "g_ptr.h"
#include "utils.h"

struct session_t {
    g_ptr_t<SoupSession> session;

    static session_t* create(GPtrArray*) {
        return new session_t{take_t{soup_session_new()}};
    }

    g_ptr_t<JSCValue> fetch(GPtrArray* params) {
        auto state = std::make_shared<message_t>();

        if (!state->init(jsc_context_get_current(), session, params)) {
            return take_t{jsc_value_new_undefined(jsc_context_get_current())};
        }

        auto executor = take(jsc_value_new_function(jsc_context_get_current(), nullptr,
            reinterpret_cast<GCallback>(+[](JSCValue* resolve, JSCValue* reject, std::shared_ptr<message_t>* message) {
                message->get()->launch(resolve, reject);
            }),
            state->ref(), destroy_adapter_shared<message_t>(), G_TYPE_NONE, 2, JSC_TYPE_VALUE, JSC_TYPE_VALUE));

        return take_t{jsc_value_constructor_call(take(jsc_context_get_value(jsc_context_get_current(), "Promise")),
            JSC_TYPE_VALUE, executor.as(), G_TYPE_NONE)};
    }

    g_ptr_t<JSCValue> download(GPtrArray* params) {
        auto state = std::make_shared<download_t>();

        if (!state->init(jsc_context_get_current(), session, params)) {
            return take_t{jsc_value_new_undefined(jsc_context_get_current())};
        }

        auto executor = take(jsc_value_new_function(jsc_context_get_current(), nullptr,
            reinterpret_cast<GCallback>(+[](JSCValue* resolve, JSCValue* reject, std::shared_ptr<download_t>* download) {
                download->get()->launch(resolve, reject);
            }),
            state->ref(), destroy_adapter_shared<download_t>(), G_TYPE_NONE, 2, JSC_TYPE_VALUE, JSC_TYPE_VALUE));

        return take_t{jsc_value_constructor_call(take(jsc_context_get_value(jsc_context_get_current(), "Promise")),
            JSC_TYPE_VALUE, executor.as(), G_TYPE_NONE)};
    }
};

void register_session_class(JSCContext* context, const char* name) {
    auto cls = g_ptr_t{jsc_context_register_class(context, name, nullptr, nullptr, destroy_adapter<session_t>())};
    jsc_context_set_value(context, jsc_class_get_name(cls),
        take(jsc_class_add_constructor_variadic(cls, nullptr, reinterpret_cast<GCallback>(+[](GPtrArray* params, void*) {
            return session_t::create(params);
        }),
            nullptr, nullptr, G_TYPE_POINTER)));
    jsc_class_add_method_variadic(
        cls, "fetch", reinterpret_cast<GCallback>(+[](session_t* session, GPtrArray* params, void*) {
            return session->fetch(params).release();
        }),
        nullptr, nullptr, JSC_TYPE_VALUE);
    jsc_class_add_method_variadic(
        cls, "download", reinterpret_cast<GCallback>(+[](session_t* session, GPtrArray* params, void*) {
            return session->download(params).release();
        }),
        nullptr, nullptr, JSC_TYPE_VALUE);
}
