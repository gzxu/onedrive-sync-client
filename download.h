#include <atomic>
#include <fstream>
#include <iostream>
#include <memory>

#include <webkit2/webkit-web-extension.h>

#include "utils.h"

struct download_t : std::enable_shared_from_this<download_t> {
    g_ptr_t<SoupSession> session;
    g_ptr_t<SoupMessage> message;
    std::string destination;
    std::size_t offset;
    std::atomic<std::size_t> progress;
    g_ptr_t<GInputStream> stream;
    g_ptr_t<GMainContext> main_context;
    g_ptr_t<JSCValue> signal;
    g_ptr_t<GCancellable> cancellable;
    g_ptr_t<JSCValue> resolve;
    g_ptr_t<JSCValue> reject;

    std::shared_ptr<download_t>* ref() {
        return new std::shared_ptr<download_t>{weak_from_this()};
    }

    bool init(JSCContext* context, SoupSession* session, GPtrArray* params) {
        switch (params->len) {
        case 0:
            jsc_context_throw(context, "Missing URL");
            return false;
        case 1:
            jsc_context_throw(context, "Missing Destination");
            return false;
        }

        auto uri = g_unique_ptr_take(soup_uri_new(string_from_jsc(static_cast<JSCValue*>(params->pdata[0])).c_str()));
        if (!uri || !uri->host) {
            jsc_context_throw(context, "Malformed URL");
            return false;
        }

        destination = string_from_jsc(static_cast<JSCValue*>(params->pdata[1]));
        offset = 0;

        if (params->len >= 3) {
            auto options = static_cast<JSCValue*>(params->pdata[2]);
            if (jsc_value_to_boolean(options)) {
                if (!jsc_value_is_object(options)) {
                    jsc_context_throw(context, "Not an Object");
                    return false;
                }

                if (auto [result, success] = int_from_jsc<std::size_t>(take(jsc_value_object_get_property(options, "offset"))); !success) {
                    jsc_context_throw(context, "Invalid offset");
                    return false;
                } else {
                    offset = result;
                }

                signal = take_t{jsc_value_object_get_property(options, "signal")};
                if (!jsc_value_to_boolean(signal)) {
                    signal = nullptr;
                } else {
                    if (!jsc_value_is_object(signal) || !jsc_value_object_is_instance_of(signal, "AbortSignal")) {
                        jsc_context_throw(context, "Not an AbortSignal");
                        return false;
                    }
                }
            }
        }

        message = take(soup_message_new_from_uri("GET", uri.get()));
        this->session = session;
        cancellable = take_t{g_cancellable_new()};
        progress = 0;

        return true;
    }

    void launch(JSCValue* resolve, JSCValue* reject) {
        this->resolve = resolve;
        this->reject = reject;

        if (signal) {
            jsc_value_object_set_property(signal, "onabort",
                jsc_value_new_function_variadic(jsc_context_get_current(), nullptr,
                    reinterpret_cast<GCallback>(+[](GPtrArray*, void* data) {
                        static_cast<std::shared_ptr<download_t>*>(data)->get()->cancel();
                    }),
                    ref(), destroy_adapter_shared<download_t>(), G_TYPE_NONE));
        }

        soup_session_send_async(session, message, cancellable,
            callback_adapter_shared<SoupSession, GInputStream*, soup_session_send_finish, download_t, &download_t::got_response>(), ref());
    }

    void transfer() {
        std::filebuf out;
        if (!out.open(this->destination, std::ios_base::app | std::ios_base::binary)) {
            g_idle_add([](void* data) -> gboolean {
                take(jsc_value_function_call(static_cast<std::shared_ptr<download_t>*>(data)->get()->reject, G_TYPE_STRING, "Fail on open", G_TYPE_NONE));
                delete static_cast<std::shared_ptr<download_t>*>(data);
                return false;
            },
                ref());
            return;
        }
        char buf[8192];
        GError* error;

        std::streamsize count;

        for (;;) {
            count = g_input_stream_read(stream, buf, 8192, cancellable, &error);
            if (!count) {
                break;
            }
            if (error) {
                g_idle_add([](void* data) -> gboolean {
                    take(jsc_value_function_call(static_cast<std::shared_ptr<download_t>*>(data)->get()->reject, G_TYPE_STRING, "Fail", G_TYPE_NONE));
                    delete static_cast<std::shared_ptr<download_t>*>(data);
                    return false;
                },
                    ref());
                return;
            }

            progress.fetch_add(count, std::memory_order_relaxed);

            std::streamsize offset = 0;
            while (offset < count) {
                offset += out.sputn(buf + offset, count - offset);
            }
        }

        g_idle_add([](void* data) -> gboolean {
            take(jsc_value_function_call(static_cast<std::shared_ptr<download_t>*>(data)->get()->resolve, G_TYPE_STRING, "Success", G_TYPE_NONE));
            delete static_cast<std::shared_ptr<download_t>*>(data);
            return false;
        },
            ref());
    }

    void got_response(g_ptr_t<GInputStream> stream, g_unique_ptr_t<GError> error) {
        if (error) {
            auto undefined = take(jsc_value_function_call(reject, G_TYPE_STRING, error->message, G_TYPE_NONE));
            return;
        }

        auto length = soup_message_headers_get_content_length(message->response_headers);
        if (!length) {
            auto undefined = take(jsc_value_function_call(reject, G_TYPE_STRING, "Empty response", G_TYPE_NONE));
            return;
        }

        this->stream = std::move(stream);
        auto result = take(jsc_value_new_object(jsc_value_get_context(resolve), nullptr, nullptr));

        jsc_value_object_set_property(result, "length", take(jsc_value_new_number(jsc_value_get_context(result), length)));

        jsc_value_object_set_property(result, "progress",
            take(jsc_value_new_function_variadic(jsc_value_get_context(result), nullptr,
                reinterpret_cast<GCallback>(+[](GPtrArray*, std::shared_ptr<download_t>* state) {
                    return string_to_jsc(std::to_string(state->get()->progress.load(std::memory_order_relaxed)), jsc_context_get_current()).release();
                }),
                ref(), destroy_adapter_shared<download_t>(), JSC_TYPE_VALUE)));

        auto executor = take(jsc_value_new_function(jsc_value_get_context(result), nullptr,
            reinterpret_cast<GCallback>(+[](JSCValue* resolve, JSCValue* reject, std::shared_ptr<download_t>* state) {
                state->get()->resolve = resolve;
                state->get()->reject = reject;
                state->get()->main_context = take_t{g_main_context_ref_thread_default()};

                take(g_thread_new(nullptr, [](void* state) -> void* {
                    static_cast<std::shared_ptr<download_t>*>(state)->get()->transfer();
                    delete static_cast<std::shared_ptr<download_t>*>(state);
                    return nullptr;
                },
                    state->get()->ref()));
            }),
            ref(), destroy_adapter_shared<download_t>(), G_TYPE_NONE, 2, JSC_TYPE_VALUE, JSC_TYPE_VALUE));

        auto resolve = std::move(this->resolve);

        jsc_value_object_set_property(result, "promise",
            take(jsc_value_constructor_call(take(jsc_context_get_value(jsc_value_get_context(result), "Promise")),
                JSC_TYPE_VALUE, executor.as(), G_TYPE_NONE)));

        take(jsc_value_function_call(resolve, JSC_TYPE_VALUE, result.as(), G_TYPE_NONE));
    }

    void cancel() {
        g_cancellable_cancel(cancellable);
    }
};
