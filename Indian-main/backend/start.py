import logging

import uvicorn


class _QuietWsDrop(logging.Filter):
    """Replace the multi-line "ConnectionClosedError ... keepalive ping
    timeout" traceback with one line. The app reconnects by itself (3s retry
    loop), so the traceback is noise, not an error."""

    def filter(self, record):
        if "ConnectionClosedError" in record.getMessage():
            print("[WS] app connection dropped (keepalive timeout) - app will reconnect")
            return False
        return True


logging.getLogger("asyncio").addFilter(_QuietWsDrop())

if __name__ == "__main__":
    print("🦉 OWL Terminal Backend Starting...")
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        # uvicorn's own WebSocket keepalive defaults to ping every 20s and
        # drop the connection if no pong arrives within 20s ("sent 1011
        # (internal error) keepalive ping timeout"). On a phone (Termux +
        # the app on the same weak LTE/Wi-Fi, app going to background, Doze)
        # 20s is easily missed, which killed the socket and made the app show
        # gaps. The app has its own 5s ping/pong + reconnect logic, so the
        # server side can be much more forgiving.
        ws_ping_interval=30,
        ws_ping_timeout=60,
        timeout_keep_alive=30,
    )
