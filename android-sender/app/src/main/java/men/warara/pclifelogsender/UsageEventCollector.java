package men.warara.pclifelogsender;

import android.app.AppOpsManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Process;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

public class UsageEventCollector {
    public static boolean hasUsageAccess(Context context) {
        AppOpsManager appOps = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
        int mode = appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.getPackageName()
        );
        return mode == AppOpsManager.MODE_ALLOWED;
    }

    public static JSONArray collect(Context context, long startMs, long endMs) throws Exception {
        UsageStatsManager manager = (UsageStatsManager) context.getSystemService(Context.USAGE_STATS_SERVICE);
        UsageEvents events = manager.queryEvents(startMs, endMs);
        UsageEvents.Event event = new UsageEvents.Event();
        Map<String, Long> foregroundStarts = new HashMap<>();
        JSONArray output = new JSONArray();

        while (events.hasNextEvent()) {
            events.getNextEvent(event);
            String packageName = event.getPackageName();
            if (packageName == null || packageName.equals(context.getPackageName())) {
                continue;
            }
            int type = event.getEventType();
            long timestamp = event.getTimeStamp();
            if (isForeground(type)) {
                foregroundStarts.put(packageName, timestamp);
            } else if (isBackground(type)) {
                Long start = foregroundStarts.remove(packageName);
                if (start != null && timestamp > start) {
                    output.put(toJson(context, packageName, start, timestamp - start));
                }
            }
        }
        return output;
    }

    private static boolean isForeground(int type) {
        return type == UsageEvents.Event.MOVE_TO_FOREGROUND || type == UsageEvents.Event.ACTIVITY_RESUMED;
    }

    private static boolean isBackground(int type) {
        return type == UsageEvents.Event.MOVE_TO_BACKGROUND || type == UsageEvents.Event.ACTIVITY_PAUSED;
    }

    private static JSONObject toJson(Context context, String packageName, long startMs, long durationMs) throws Exception {
        JSONObject event = new JSONObject();
        event.put("timestamp", iso(startMs));
        event.put("duration", durationMs / 1000.0);
        JSONObject data = new JSONObject();
        data.put("app", appLabel(context, packageName));
        data.put("package", packageName);
        data.put("source", "android-sender");
        event.put("data", data);
        return event;
    }

    private static String appLabel(Context context, String packageName) {
        try {
            PackageManager pm = context.getPackageManager();
            ApplicationInfo info = pm.getApplicationInfo(packageName, 0);
            CharSequence label = pm.getApplicationLabel(info);
            return label == null ? packageName : label.toString();
        } catch (Exception ignored) {
            return packageName;
        }
    }

    private static String iso(long timestampMs) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(timestampMs));
    }
}
