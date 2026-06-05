package men.warara.pclifelogsender;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

public class PairingConfig {
    private static final String PREFS = "pc_lifelog_sender";
    private static final String KEY_JSON = "pairing_json";
    private static final String KEY_LAST_ENDPOINT = "last_endpoint";
    private static final String KEY_LAST_SYNC = "last_sync";

    public final String token;
    public final List<Endpoint> endpoints;

    public PairingConfig(String token, List<Endpoint> endpoints) {
        this.token = token;
        this.endpoints = endpoints;
    }

    public static PairingConfig parse(String raw) throws Exception {
        JSONObject root = new JSONObject(raw);
        String token = root.optString("token", "");
        List<Endpoint> endpoints = new ArrayList<>();
        JSONArray array = root.optJSONArray("endpoints");
        if (array != null) {
            for (int i = 0; i < array.length(); i++) {
                JSONObject item = array.optJSONObject(i);
                if (item != null) {
                    Endpoint endpoint = Endpoint.fromJson(item);
                    if (endpoint.url != null && endpoint.url.startsWith("http")) {
                        endpoints.add(endpoint);
                    }
                }
            }
        }
        String server = root.optString("server", "");
        if (server.startsWith("http")) {
            endpoints.add(new Endpoint("server", server, 5));
        }
        Collections.sort(endpoints, Comparator.comparingInt(e -> e.priority));
        if (token.isEmpty() || endpoints.isEmpty()) {
            throw new IllegalArgumentException("QR does not contain token/endpoints");
        }
        return new PairingConfig(token, endpoints);
    }

    public static void save(Context context, String rawJson) {
        prefs(context).edit().putString(KEY_JSON, rawJson).apply();
    }

    public static PairingConfig load(Context context) throws Exception {
        String raw = prefs(context).getString(KEY_JSON, "");
        if (raw == null || raw.isEmpty()) {
            throw new IllegalStateException("Not paired");
        }
        return parse(raw);
    }

    public static boolean hasConfig(Context context) {
        return prefs(context).contains(KEY_JSON);
    }

    public static String getLastEndpoint(Context context) {
        return prefs(context).getString(KEY_LAST_ENDPOINT, "");
    }

    public static void setLastEndpoint(Context context, String endpoint) {
        prefs(context).edit().putString(KEY_LAST_ENDPOINT, endpoint).apply();
    }

    public static long getLastSync(Context context) {
        return prefs(context).getLong(KEY_LAST_SYNC, 0L);
    }

    public static void setLastSync(Context context, long value) {
        prefs(context).edit().putLong(KEY_LAST_SYNC, value).apply();
    }

    public static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
