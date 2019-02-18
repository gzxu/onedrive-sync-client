#pragma once

#include <memory>

#include <webkit2/webkit-web-extension.h>

#include "g_ptr.h"
#include "utils.h"

struct message_t : std::enable_shared_from_this<message_t> {
    g_ptr_t<SoupSession> session;
    g_ptr_t<SoupMessage> message;
    g_ptr_t<JSCValue> signal;
    g_ptr_t<JSCValue> progress;
    g_ptr_t<GCancellable> cancellable;
    g_ptr_t<JSCValue> resolve;
    g_ptr_t<JSCValue> reject;
    g_ptr_t<GMemoryOutputStream> out;

    std::shared_ptr<message_t>* ref() {
        return new std::shared_ptr<message_t>{weak_from_this()};
    }

    bool init(JSCContext* context, SoupSession* session, GPtrArray* params) {
        if (params->len < 1) {
            jsc_context_throw(context, "Missing URL");
            return false;
        }

        auto uri = g_unique_ptr_take(soup_uri_new(string_from_jsc(static_cast<JSCValue*>(params->pdata[0])).c_str()));
        if (!uri || !uri->host) {
            jsc_context_throw(context, "Malformed URL");
            return false;
        }

        auto method = "GET"s;
        auto data = ""s;
        g_ptr_t<JSCValue> headers;

        if (params->len >= 2) {
            auto options = static_cast<JSCValue*>(params->pdata[1]);
            if (jsc_value_to_boolean(options)) {
                if (!jsc_value_is_object(options)) {
                    jsc_context_throw(context, "Not an Object");
                    return false;
                }

                method = string_from_jsc(take(jsc_value_object_get_property(options, "method")));
                if (!method.size()) {
                    method = "GET"s;
                }
                data = string_from_jsc(take(jsc_value_object_get_property(options, "data")));

                headers = take_t{jsc_value_object_get_property(options, "headers")};
                if (!jsc_value_to_boolean(headers)) {
                    headers = nullptr;
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

                progress = take_t{jsc_value_object_get_property(options, "onConnect")};
                if (!jsc_value_to_boolean(progress)) {
                    progress = nullptr;
                } else {
                    if (!jsc_value_is_function(progress)) {
                        jsc_context_throw(context, "Not a Function");
                        return false;
                    }
                }
            }
        }

        message = take(soup_message_new_from_uri(method.c_str(), uri.get()));
        if (headers) {
            if (auto keys = g_unique_ptr_take(jsc_value_object_enumerate_properties(headers))) {
                for (auto iter = keys.get(); *iter; iter++) {
                    auto value = string_from_jsc(take(jsc_value_object_get_property(headers, *iter)));
                    soup_message_headers_append(message->request_headers, *iter, value.c_str());
                }
            }
        }
        if (data.size()) {
            auto string = new std::string{std::move(data)};
            auto buffer = take(soup_buffer_new_with_owner(string->data(), string->size(), string, destroy_adapter<std::string>()));
            soup_message_body_append_buffer(message->request_body, buffer);
        }

        this->session = session;
        cancellable = take_t{g_cancellable_new()};

        return true;
    }

    void launch(JSCValue* resolve, JSCValue* reject) {
        this->resolve = resolve;
        this->reject = reject;

        if (signal) {
            jsc_value_object_set_property(signal, "onabort",
                jsc_value_new_function_variadic(jsc_context_get_current(), nullptr,
                    reinterpret_cast<GCallback>(+[](GPtrArray*, void* data) {
                        static_cast<std::shared_ptr<message_t>*>(data)->get()->cancel();
                    }),
                    ref(), destroy_adapter_shared<message_t>(), G_TYPE_NONE));
        }

        soup_session_send_async(session, message, cancellable,
            callback_adapter_shared<SoupSession, GInputStream*, soup_session_send_finish, message_t, &message_t::got_response>(), ref());
    }

    void got_response(g_ptr_t<GInputStream> stream, g_unique_ptr_t<GError> error) {
        if (error) {
            auto undefined = take(jsc_value_function_call(reject, G_TYPE_STRING, error->message, G_TYPE_NONE));
            return;
        }

        if (progress) {
            auto undefined = take(jsc_value_function_call(progress,
                G_TYPE_UINT, message->status_code,
                JSC_TYPE_VALUE, headers_to_jsc(message->response_headers, jsc_value_get_context(progress)).as(),
                G_TYPE_NONE));
        }

        out = take_t<GMemoryOutputStream>{g_memory_output_stream_new_resizable()};
        g_output_stream_splice_async(out.as<GOutputStream>(), stream,
            static_cast<GOutputStreamSpliceFlags>(G_OUTPUT_STREAM_SPLICE_CLOSE_SOURCE | G_OUTPUT_STREAM_SPLICE_CLOSE_TARGET),
            G_PRIORITY_DEFAULT, cancellable,
            callback_adapter_shared<GOutputStream, gssize, g_output_stream_splice_finish, message_t, &message_t::transfer_finish>(), ref());
    }

    void transfer_finish(gssize, g_unique_ptr_t<GError> error) {
        if (error) {
            auto undefined = take(jsc_value_function_call(reject, G_TYPE_STRING, error->message, G_TYPE_NONE));
            return;
        }

        auto context = jsc_value_get_context(resolve);

        auto bytes = take(g_bytes_new_static(g_memory_output_stream_get_data(out), g_memory_output_stream_get_data_size(out)));
        auto string = take(jsc_value_new_string_from_bytes(context, bytes));

        if (progress) {
            auto undefined = take(jsc_value_function_call(resolve, JSC_TYPE_VALUE, string.as(), G_TYPE_NONE));
        } else {
            auto result = take(jsc_value_new_object(context, nullptr, nullptr));
            jsc_value_object_set_property(result, "body", string);
            jsc_value_object_set_property(result, "status", jsc_value_new_number(context, static_cast<double>(message->status_code)));
            jsc_value_object_set_property(result, "headers", headers_to_jsc(message->response_headers, context));
            auto undefined = take(jsc_value_function_call(resolve, JSC_TYPE_VALUE, result.as(), G_TYPE_NONE));
        }
    }

    void cancel() {
        g_cancellable_cancel(this->cancellable);
    }
};
