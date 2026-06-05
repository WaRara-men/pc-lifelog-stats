package men.warara.pclifelogsender;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;

public class SyncWorker extends Worker {
    public static final String UNIQUE_WORK = "pc_lifelog_sender_periodic";

    public SyncWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        try {
            syncNow(getApplicationContext());
            return Result.success();
        } catch (Exception ex) {
            return Result.retry();
        }
    }

    public static int syncNow(Context context) throws Exception {
        PairingConfig config = PairingConfig.load(context);
        if (!UsageEventCollector.hasUsageAccess(context)) {
            throw new IllegalStateException("Usage access is not granted");
        }

        long now = System.currentTimeMillis();
        long last = PairingConfig.getLastSync(context);
        long start = last > 0 ? Math.max(0, last - 30 * 60 * 1000L) : now - 24 * 60 * 60 * 1000L;
        JSONArray fresh = UsageEventCollector.collect(context, start, now);
        EventQueue.append(context, fresh);
        JSONArray pending = EventQueue.load(context);
        if (pending.length() > 0) {
            SenderClient.postEvents(context, config, pending);
            EventQueue.clear(context);
        }
        PairingConfig.setLastSync(context, now);
        return pending.length();
    }
}
