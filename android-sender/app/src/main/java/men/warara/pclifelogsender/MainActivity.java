package men.warara.pclifelogsender;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import com.google.android.gms.tasks.OnFailureListener;
import com.google.android.gms.tasks.OnSuccessListener;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import com.google.mlkit.vision.barcode.common.Barcode;

import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class MainActivity extends Activity {
    private TextView status;
    private TextView details;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildView());
        refreshStatus();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
    }

    private View buildView() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 42, 36, 36);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("PC Lifelog Sender");
        title.setTextSize(24);
        title.setGravity(Gravity.START);
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("QR is needed only once. After pairing, this app syncs Android screen time to your PC automatically.");
        subtitle.setTextSize(14);
        subtitle.setPadding(0, 8, 0, 24);
        root.addView(subtitle);

        status = new TextView(this);
        status.setTextSize(16);
        status.setPadding(0, 0, 0, 12);
        root.addView(status);

        details = new TextView(this);
        details.setTextSize(13);
        details.setPadding(0, 0, 0, 22);
        root.addView(details);

        root.addView(button("Scan pairing QR", v -> scanQr()));
        root.addView(button("Grant usage access", v -> openUsageAccess()));
        root.addView(button("Sync now", v -> syncNow()));
        root.addView(button("Start 15-minute auto sync", v -> startPeriodicSync()));
        root.addView(button("Battery optimization settings", v -> openBatterySettings()));
        return scroll;
    }

    private Button button(String label, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setOnClickListener(listener);
        button.setPadding(0, 8, 0, 8);
        return button;
    }

    private void scanQr() {
        GmsBarcodeScanner scanner = GmsBarcodeScanning.getClient(this);
        scanner.startScan()
                .addOnSuccessListener(new OnSuccessListener<Barcode>() {
                    @Override
                    public void onSuccess(Barcode barcode) {
                        String raw = barcode.getRawValue();
                        if (raw == null || raw.isEmpty()) {
                            toast("QR was empty");
                            return;
                        }
                        try {
                            PairingConfig.parse(raw);
                            PairingConfig.save(MainActivity.this, raw);
                            startPeriodicSync();
                            toast("Paired. QR is no longer needed.");
                            refreshStatus();
                        } catch (Exception ex) {
                            toast("Invalid QR: " + ex.getMessage());
                        }
                    }
                })
                .addOnFailureListener(new OnFailureListener() {
                    @Override
                    public void onFailure(Exception e) {
                        toast("Scan failed: " + e.getMessage());
                    }
                });
    }

    private void openUsageAccess() {
        startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
    }

    private void openBatterySettings() {
        try {
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            intent.setData(Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception ignored) {
            startActivity(new Intent(Settings.ACTION_SETTINGS));
        }
    }

    private void syncNow() {
        Executors.newSingleThreadExecutor().execute(() -> {
            try {
                int sent = SyncWorker.syncNow(MainActivity.this);
                runOnUiThread(() -> {
                    toast("Synced " + sent + " events");
                    refreshStatus();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> toast("Sync failed: " + ex.getMessage()));
            }
        });
    }

    private void startPeriodicSync() {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.UNMETERED)
                .build();
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(SyncWorker.class, 15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build();
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                SyncWorker.UNIQUE_WORK,
                ExistingPeriodicWorkPolicy.UPDATE,
                request
        );
        toast("Auto sync scheduled");
        refreshStatus();
    }

    private void refreshStatus() {
        boolean paired = PairingConfig.hasConfig(this);
        boolean usage = UsageEventCollector.hasUsageAccess(this);
        int pending = EventQueue.count(this);
        String lastEndpoint = PairingConfig.getLastEndpoint(this);
        long lastSync = PairingConfig.getLastSync(this);

        status.setText("Paired: " + yesNo(paired) + " / Usage access: " + yesNo(usage));
        StringBuilder builder = new StringBuilder();
        builder.append("Pending events: ").append(pending).append("\n");
        builder.append("Last endpoint: ").append(lastEndpoint == null || lastEndpoint.isEmpty() ? "-" : lastEndpoint).append("\n");
        builder.append("Last sync: ").append(lastSync > 0 ? new java.util.Date(lastSync).toString() : "-").append("\n");
        details.setText(builder.toString());
    }

    private String yesNo(boolean value) {
        return value ? "OK" : "Not yet";
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }
}
