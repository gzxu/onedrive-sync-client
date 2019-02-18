/**
 * Smart pointer for GLib
 * 
 * Inspired by
 * https://github.com/WebKit/webkit/blob/master/Source/WTF/wtf/glib/GRefPtr.h
 * and https://github.com/WebKit/webkit/blob/master/Source/WTF/wtf/glib/GUniquePtr.h
 */

#pragma once

#include <memory>

#include <glib.h>
#include <libsoup/soup.h>

template<typename T>
inline T* g_ptr_ref(T* ptr) {
    if (ptr) {
        g_ptr_ref_impl(ptr);
    }
    return ptr;
}

template<typename T>
inline void g_ptr_unref(T* ptr) {
    if (ptr) {
        g_ptr_unref_impl(ptr);
    }
}

template<typename T>
inline void g_ptr_ref_impl(T* ptr) {
    g_object_ref_sink(ptr);
}

template<typename T>
inline void g_ptr_unref_impl(T* ptr) {
    g_object_unref(ptr);
}

template<>
inline void g_ptr_ref_impl(GBytes* ptr) {
    g_bytes_ref(ptr);
}

template<>
inline void g_ptr_unref_impl(GBytes* ptr) {
    g_bytes_unref(ptr);
}

template<>
inline void g_ptr_ref_impl(SoupBuffer* ptr) {
    soup_buffer_copy(ptr);
}

template<>
inline void g_ptr_unref_impl(SoupBuffer* ptr) {
    soup_buffer_free(ptr);
}

template<>
inline void g_ptr_ref_impl(GThread* ptr) {
    g_thread_ref(ptr);
}

template<>
inline void g_ptr_unref_impl(GThread* ptr) {
    g_thread_unref(ptr);
}

template<>
inline void g_ptr_ref_impl(GMainContext* ptr) {
    g_main_context_ref(ptr);
}

template<>
inline void g_ptr_unref_impl(GMainContext* ptr) {
    g_main_context_unref(ptr);
}

template<typename T>
struct take_t {
    T* ptr;
    take_t(T* ptr)
        : ptr(ptr) {}
    template<typename U>
    take_t(U* ptr)
        : ptr(reinterpret_cast<T*>(ptr)) {}
};

template<typename T>
struct g_ptr_t {
    struct deleter {
        void operator()(T* ptr) const {
            g_ptr_unref(ptr);
        }
    };
    g_ptr_t() = default;
    g_ptr_t(g_ptr_t<T>&&) = default;
    g_ptr_t<T>& operator=(g_ptr_t<T>&& other) = default;

    g_ptr_t(const g_ptr_t<T>& other)
        : g_ptr_t(other.as()) {}

    g_ptr_t<T>& operator=(const g_ptr_t<T>& other) {
        return operator=(other.as());
    }

    g_ptr_t(T* ptr)
        : wrapped_ptr(g_ptr_ref(ptr)) {}

    g_ptr_t<T>& operator=(T* ptr) {
        wrapped_ptr.reset(g_ptr_ref(ptr));
        return *this;
    }

    g_ptr_t(take_t<T> taken)
        : wrapped_ptr(taken.ptr) {}

    g_ptr_t<T>& operator=(take_t<T> taken) {
        wrapped_ptr.reset(taken.ptr);
        return *this;
    }

    template<typename U = T>
    U* as() const {
        return reinterpret_cast<U*>(wrapped_ptr.get());
    }

    [[gnu::warn_unused_result]] T* release() {
        return wrapped_ptr.release();
    }

    T*
    operator->() const noexcept {
        return as();
    }

    explicit operator bool() const noexcept {
        return !!wrapped_ptr;
    }

    operator T*() const noexcept {
        return as();
    }

private:
    std::unique_ptr<T, deleter> wrapped_ptr;
};

template<typename T>
auto take(T* ptr) {
    return g_ptr_t{take_t{ptr}};
}

template<typename T>
inline void g_delete_func(T* ptr) {
    g_free(ptr);
}

template<>
inline void g_delete_func(GError* ptr) {
    g_error_free(ptr);
}

template<>
inline void g_delete_func(char** ptr) {
    g_strfreev(ptr);
}

template<>
inline void g_delete_func(SoupURI* ptr) {
    soup_uri_free(ptr);
}

template<typename T>
struct g_ptr_deleter {
    void operator()(T* ptr) const {
        if (ptr) {
            g_delete_func(ptr);
        }
    }
};

template<typename T>
using g_unique_ptr_t = std::unique_ptr<T, g_ptr_deleter<T>>;

template<typename T>
auto g_unique_ptr_take(T* ptr) {
    return g_unique_ptr_t<T>{ptr};
}
