package men.warara.pclifelogsender;

import android.content.Context;

import org.json.JSONArray;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

public class EventQueue {
    private static final String FILE_NAME = "pending_events.json";

    public static synchronized JSONArray load(Context context) {
        File file = new File(context.getFilesDir(), FILE_NAME);
        if (!file.exists()) {
            return new JSONArray();
        }
        try {
            String raw = new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
            return new JSONArray(raw);
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    public static synchronized void save(Context context, JSONArray events) throws Exception {
        File file = new File(context.getFilesDir(), FILE_NAME);
        Files.write(file.toPath(), events.toString().getBytes(StandardCharsets.UTF_8));
    }

    public static synchronized void append(Context context, JSONArray events) throws Exception {
        JSONArray current = load(context);
        for (int i = 0; i < events.length(); i++) {
            current.put(events.get(i));
        }
        save(context, current);
    }

    public static synchronized void clear(Context context) throws Exception {
        save(context, new JSONArray());
    }

    public static synchronized int count(Context context) {
        return load(context).length();
    }
}
