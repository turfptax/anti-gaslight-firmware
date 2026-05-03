"""
MQTT publisher.

Thin wrapper over umqtt.robust (auto-reconnects on disconnect). One MQTTClient
per node. Topic tree and payload schema in docs/mqtt_topics.md.

Why robust over simple:
  Wall-powered nodes run for weeks; transient broker hiccups must not require
  a reboot. robust.MQTTClient catches OSError on publish and reconnects
  silently. simple.MQTTClient would raise and we'd have to hand-roll the
  reconnect.
"""

try:
    from umqtt.robust import MQTTClient
except ImportError:
    MQTTClient = None       # allows host-side import for unit tests


class MQTTPublisher:
    def __init__(self, mqtt_cfg, client_id):
        """
        mqtt_cfg: {
            "host": str, "port": int (default 1883),
            "username": optional, "password": optional,
            "keepalive_s": int (default 60),
        }
        """
        self._cfg = mqtt_cfg
        self._client_id = client_id
        self._client = None

    def connect(self):
        if MQTTClient is None:
            raise RuntimeError("umqtt.robust not available")

        self._client = MQTTClient(
            client_id=self._client_id,
            server=self._cfg["host"],
            port=self._cfg.get("port", 1883),
            user=self._cfg.get("username") or None,
            password=self._cfg.get("password") or None,
            keepalive=self._cfg.get("keepalive_s", 60),
        )

        # Last-will: broker publishes "offline" to our status topic if we
        # drop without a clean DISCONNECT. main.py publishes "online" after
        # connect() returns.
        status_topic = "anti-gaslight/{}/status".format(self._client_id)
        self._client.set_last_will(status_topic, b"offline", retain=True, qos=1)

        self._client.connect()
        print("[mqtt] connected to {}:{}".format(
            self._cfg["host"], self._cfg.get("port", 1883)))

    def publish(self, topic, payload, retain=False, qos=0):
        """Publish a payload. umqtt.robust handles reconnect on transient failure."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self._client.publish(topic, payload, retain=retain, qos=qos)

    def subscribe(self, topic, qos=0):
        """Subscribe to a topic. Pair with set_callback() for delivery."""
        if isinstance(topic, str):
            topic = topic.encode("utf-8")
        self._client.subscribe(topic, qos=qos)
        print("[mqtt] subscribed to", topic)

    def set_callback(self, callback):
        """
        Register a function for incoming subscribed messages.

        callback(topic_bytes, payload_bytes) -- both are raw bytes from the
        client. The caller is responsible for decoding / JSON-parsing.
        """
        self._client.set_callback(callback)

    def loop(self):
        """Service the client. Call from main loop to drive keepalive + subs."""
        try:
            self._client.check_msg()
        except OSError:
            # robust will reconnect on next publish; nothing to do here
            pass

    def disconnect(self):
        try:
            self._client.disconnect()
        except Exception:
            pass
