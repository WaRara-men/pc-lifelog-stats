package men.warara.pclifelogsender;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class SenderClient {
    public static String pingBestEndpoint(Context context, PairingConfig config) throws Exception {
        List<Endpoint> endpoints = orderedEndpoints(context, config);
        Exception last = null;
        for (Endpoint endpoint : endpoints) {
            try {
                URL url = new URL(endpoint.url + "/api/android/ping?token=" + encode(config.token));
                HttpURLConnection connection = (HttpURLConnection) url.openConnection();
                connection.setConnectTimeout(3500);
                connection.setReadTimeout(3500);
                connection.setRequestMethod("GET");
                int code = connection.getResponseCode();
                if (code >= 200 && code < 300) {
                    PairingConfig.setLastEndpoint(context, endpoint.url);
                    return endpoint.url;
                }
            } catch (Exception ex) {
                last = ex;
            }
        }
        if (last != null) {
            throw last;
        }
        throw new IllegalStateException("No endpoint");
    }

    public static void postEvents(Context context, PairingConfig config, JSONArray events) throws Exception {
        String endpoint = pingBestEndpoint(context, config);
        URL url = new URL(endpoint + "/api/android/events?token=" + encode(config.token));
        JSONObject payload = new JSONObject();
        payload.put("events", events);
        byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);

        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setConnectTimeout(6000);
        connection.setReadTimeout(10000);
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setDoOutput(true);
        try (OutputStream output = connection.getOutputStream()) {
            output.write(body);
        }
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) {
            String message = readResponse(connection);
            throw new IllegalStateException("POST failed: " + code + " " + message);
        }
    }

    private static List<Endpoint> orderedEndpoints(Context context, PairingConfig config) {
        String last = PairingConfig.getLastEndpoint(context);
        List<Endpoint> endpoints = new ArrayList<>();
        if (last != null && !last.isEmpty()) {
            endpoints.add(new Endpoint("last", last, -1));
        }
        endpoints.addAll(config.endpoints);
        return endpoints;
    }

    private static String encode(String value) throws Exception {
        return URLEncoder.encode(value, "UTF-8");
    }

    private static String readResponse(HttpURLConnection connection) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getErrorStream(), StandardCharsets.UTF_8))) {
            StringBuilder builder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
            return builder.toString();
        } catch (Exception ignored) {
            return "";
        }
    }
}
