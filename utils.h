#pragma once

#include <charconv>
#include <functional>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>

#include <gio/gio.h>
#include <webkit2/webkit-web-extension.h>

#include "g_ptr.h"

using namespace std::string_literals;

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**)>
auto callback_adapter() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto callback = static_cast<std::function<void(R, g_unique_ptr_t<GError>)>*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (*callback)(result, g_unique_ptr_take(error));
        delete callback;
    };
}

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**), typename T, void (T::*C)(g_ptr_t<typename std::remove_pointer_t<R>>, g_unique_ptr_t<GError>)>
auto callback_adapter() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto state = static_cast<T*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (state->*C)(g_ptr_t{take_t{result}}, g_unique_ptr_take(error));
    };
}

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**), typename T, void (T::*C)(R, g_unique_ptr_t<GError>)>
auto callback_adapter() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto state = static_cast<T*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (state->*C)(result, g_unique_ptr_take(error));
    };
}

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**), typename T, void (T::*C)(g_ptr_t<typename std::remove_pointer_t<R>>, g_unique_ptr_t<GError>, std::shared_ptr<T>*)>
auto callback_adapter() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto state = static_cast<std::shared_ptr<T>*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (state->get()->*C)(g_ptr_t{take_t{result}}, g_unique_ptr_take(error), state);
    };
}

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**), typename T, void (T::*C)(R, g_unique_ptr_t<GError>, std::shared_ptr<T>*)>
auto callback_adapter() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto state = static_cast<std::shared_ptr<T>*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (state->get()->*C)(result, g_unique_ptr_take(error), state);
    };
}

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**), typename T, void (T::*C)(g_ptr_t<typename std::remove_pointer_t<R>>, g_unique_ptr_t<GError>)>
auto callback_adapter_shared() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto state = static_cast<std::shared_ptr<T>*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (state->get()->*C)(g_ptr_t{take_t{result}}, g_unique_ptr_take(error));
        delete state;
    };
}

template<typename S, typename R, R (*F)(S*, GAsyncResult*, GError**), typename T, void (T::*C)(R, g_unique_ptr_t<GError>)>
auto callback_adapter_shared() {
    return +[](GObject* source_object, GAsyncResult* res, void* user_data) {
        GError* error{};
        auto state = static_cast<std::shared_ptr<T>*>(user_data);
        auto result = F(reinterpret_cast<S*>(source_object), res, &error);
        (state->get()->*C)(result, g_unique_ptr_take(error));
        delete state;
    };
}

template<typename T>
auto destroy_adapter() {
    return +[](void* data) {
        delete static_cast<T*>(data);
    };
}

template<typename T>
auto destroy_adapter_shared() {
    return +[](void* data) {
        delete static_cast<std::shared_ptr<T>*>(data);
    };
}

template<typename T>
std::tuple<T, bool> int_from_jsc(JSCValue* value) {
    std::size_t size;
    auto bytes = g_ptr_t{take_t{jsc_value_to_string_as_bytes(value)}};
    auto data = static_cast<const char*>(g_bytes_get_data(bytes, &size));

    T result;
    if (auto [ptr, error] = std::from_chars(data, data + size, result); error == std::errc()) {
        return {result, true};
    } else {
        return {T(), false};
    }
}

std::string string_from_jsc(JSCValue* value) {
    if (jsc_value_to_boolean(value)) {
        std::size_t size;
        auto bytes = g_ptr_t{take_t{jsc_value_to_string_as_bytes(value)}};
        auto data = static_cast<const char*>(g_bytes_get_data(bytes, &size));
        return {data, size};
    } else {
        return ""s;
    }
}

g_ptr_t<JSCValue> string_to_jsc(const std::string& data, JSCContext* context = jsc_context_get_current()) {
    return take_t{jsc_value_new_string_from_bytes(context, g_ptr_t{take_t{g_bytes_new_static(data.data(), data.size())}})};
}

g_ptr_t<JSCValue> headers_to_jsc(SoupMessageHeaders* headers, JSCContext* context = jsc_context_get_current()) {
    auto result = g_ptr_t{take_t{jsc_value_constructor_call(g_ptr_t{take_t{jsc_context_get_value(context, "Headers")}}, G_TYPE_NONE)}};

    SoupMessageHeadersIter iter;
    soup_message_headers_iter_init(&iter, headers);
    const char* name;
    const char* value;
    while (soup_message_headers_iter_next(&iter, &name, &value)) {
        auto undefined = g_ptr_t{take_t{jsc_value_object_invoke_method(result, "append", G_TYPE_STRING, name, G_TYPE_STRING, value, G_TYPE_NONE)}};
    }

    return result;
}

template<typename... Ts, std::size_t... Is>
auto tuple_from_array(GPtrArray* params, std::index_sequence<Is...>) {
    return std::make_tuple(static_cast<Ts*>(params->len > Is ? params->pdata[Is] : nullptr)...);
}

template<typename... Ts>
std::tuple<Ts*...> tuple_from_array(GPtrArray* params) {
    if (!params) return {};

    return tuple_from_array<Ts...>(params, std::index_sequence_for<Ts...>{});
}

template<std::size_t... Is>
auto js_from_array(GPtrArray* params, std::index_sequence<Is...>) {
    return std::make_tuple(g_ptr_t<JSCValue>{static_cast<JSCValue*>(params->len > Is ? params->pdata[Is] : nullptr)}...);
}

template<std::size_t I>
auto js_from_array(GPtrArray* params) {
    if (!params) return decltype(js_from_array(params, std::make_index_sequence<I>{})){};

    return js_from_array(params, std::make_index_sequence<I>{});
}
