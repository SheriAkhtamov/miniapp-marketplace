from typing import Any

from fastapi.templating import Jinja2Templates as FastAPIJinja2Templates


class Jinja2Templates(FastAPIJinja2Templates):
    def TemplateResponse(self, *args: Any, **kwargs: Any):
        # Compatibility shim for older call sites:
        # templates.TemplateResponse("template.html", {"request": request, ...})
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.pop("context", {})
            if "request" not in context:
                raise ValueError("context must include 'request'")

            request = context["request"]
            status_code = kwargs.pop("status_code", 200)
            headers = kwargs.pop("headers", None)
            media_type = kwargs.pop("media_type", None)
            background = kwargs.pop("background", None)

            return super().TemplateResponse(
                request,
                name,
                context,
                status_code=status_code,
                headers=headers,
                media_type=media_type,
                background=background,
                **kwargs,
            )

        return super().TemplateResponse(*args, **kwargs)
