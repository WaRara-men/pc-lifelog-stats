package men.warara.pclifelogsender;

import org.json.JSONObject;

public class Endpoint {
    public final String type;
    public final String url;
    public final int priority;

    public Endpoint(String type, String url, int priority) {
        this.type = type == null ? "endpoint" : type;
        this.url = url;
        this.priority = priority;
    }

    public static Endpoint fromJson(JSONObject object) {
        return new Endpoint(
                object.optString("type", "endpoint"),
                object.optString("url", ""),
                object.optInt("priority", 9)
        );
    }
}
