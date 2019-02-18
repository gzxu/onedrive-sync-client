#include <string>

#include <webkit2/webkit-web-extension.h>

#include "g_ptr.h"

using namespace std::string_literals;

void register_session_class(JSCContext* context, const char* name);

extern "C" [[gnu::visibility("default")]] void webkit_web_extension_initialize(WebKitWebExtension*) {
    g_signal_connect(webkit_script_world_get_default(), "window-object-cleared",
        reinterpret_cast<GCallback>(+[](WebKitScriptWorld* world, WebKitWebPage*, WebKitFrame* frame, void*) {
            auto context = take(webkit_frame_get_js_context_for_script_world(frame, world));

            register_session_class(context, "NativeSession");

            g_object_ref(context);
        }),
        nullptr);
}
