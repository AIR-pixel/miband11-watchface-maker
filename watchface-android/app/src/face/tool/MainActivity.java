package face.tool;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.util.Locale;

/**
 * 手环 11 动态表盘制作工具 —— 安卓端主界面。
 * 导入视频/图片 → 框选裁剪区 → 选截取区间/帧率/帧数上限/压缩/格式 → 生成 .face。
 *
 * 体积控制的第一杠杆是帧数（时长 x 帧率），所以截取区间和帧数上限放在显眼位置。
 */
public final class MainActivity extends Activity {

    private static final int REQ_PICK = 1;

    private static final String[] LEVEL_KEYS =
        {"high", "balanced", "small", "tiny", "micro", "nano"};
    private static final int[] FPS_VALUES = {6, 8, 12, 16, 20, 24, 30};
    private static final int[] MAXFRAME_VALUES = {96, 64, 48, 32, 128, 192, 240};

    private Uri sourceUri;
    private String srcType = "video";
    private double srcDurationMs = 0;

    private TextView fileLabel;
    private TextView cropLabel;
    private TextView estLabel;
    private TextView status;
    private CropView cropView;
    private Spinner levelSpinner;
    private Spinner fpsSpinner;
    private Spinner fmtSpinner;
    private Spinner jpgQSpinner;
    private Spinner maxFrameSpinner;
    private EditText startEdit;
    private EditText durEdit;
    private CheckBox speedupCheck;
    private Button genBtn;
    private ProgressBar progress;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable estRunner = new Runnable() {
        @Override public void run() { updateEstimate(); }
    };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        buildUi();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(10), dp(8), dp(10), dp(8));

        Button pick = new Button(this);
        pick.setText("选择视频 / 图片");
        pick.setOnClickListener(v -> pickFile());
        root.addView(pick);

        fileLabel = new TextView(this);
        fileLabel.setText("未选择");
        fileLabel.setGravity(Gravity.CENTER);
        root.addView(fileLabel);

        cropView = new CropView(this);
        cropView.setBackgroundColor(0xFF282828);
        root.addView(cropView, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout cropRow = new LinearLayout(this);
        cropRow.setOrientation(LinearLayout.HORIZONTAL);
        Button resetBtn = new Button(this);
        resetBtn.setText("重置裁剪框");
        resetBtn.setOnClickListener(v -> cropView.resetCrop());
        cropRow.addView(resetBtn, new LinearLayout.LayoutParams(0, dp(44), 1f));
        Button fillBtn = new Button(this);
        fillBtn.setText("铺满画面");
        fillBtn.setOnClickListener(v -> cropView.fillCrop());
        cropRow.addView(fillBtn, new LinearLayout.LayoutParams(0, dp(44), 1f));
        root.addView(cropRow);

        cropLabel = new TextView(this);
        cropLabel.setText("拖动移动 · 右下角拖动/双指缩放");
        cropLabel.setGravity(Gravity.CENTER);
        root.addView(cropLabel);
        cropView.setOnCropChanged((x0, y0, x1, y1) -> {
            cropLabel.setText("裁剪: (" + x0 + "," + y0 + ") → (" + x1 + "," + y1 + ")");
            scheduleEstimate();
        });

        LinearLayout row1 = new LinearLayout(this);
        levelSpinner = spinner(new String[]{
            "高画质 RGB", "均衡 P256", "小体积 P128", "极限 P64", "极小 P32", "微缩 P16"}, 1);
        row1.addView(levelSpinner, weight());
        fpsSpinner = spinner(new String[]{
            "6 FPS", "8 FPS", "12 FPS", "16 FPS", "20 FPS", "24 FPS", "30 FPS"}, 2);
        row1.addView(fpsSpinner, weight());
        root.addView(row1);

        LinearLayout row2 = new LinearLayout(this);
        fmtSpinner = spinner(new String[]{"PNG（无损）", "JPEG（有损·更小）"}, 0);
        row2.addView(fmtSpinner, weight());
        maxFrameSpinner = spinner(new String[]{
            "96 帧", "64 帧", "48 帧", "32 帧", "128 帧", "192 帧", "240 帧"}, 0);
        row2.addView(maxFrameSpinner, weight());
        root.addView(row2);

        LinearLayout row2b = new LinearLayout(this);
        TextView jqLabel = new TextView(this);
        jqLabel.setText("JPEG 质量");
        jqLabel.setGravity(Gravity.CENTER_VERTICAL);
        row2b.addView(jqLabel, weight());
        String[] qLabels = new String[FaceGenerator.JPG_QUALITY_OPTIONS.length];
        for (int i = 0; i < qLabels.length; i++) {
            qLabels[i] = "q" + FaceGenerator.JPG_QUALITY_OPTIONS[i];
        }
        jpgQSpinner = spinner(qLabels, 2);   // 默认 q80
        row2b.addView(jpgQSpinner, weight());
        root.addView(row2b);

        fmtSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                jpgQSpinner.setEnabled(pos == 1);
                scheduleEstimate();
            }
            @Override public void onNothingSelected(AdapterView<?> p) {}
        });
        jpgQSpinner.setEnabled(false);

        LinearLayout row3 = new LinearLayout(this);
        startEdit = numEdit("起始 秒");
        startEdit.setText("0");
        row3.addView(startEdit, weight());
        durEdit = numEdit("时长 秒 (空=全片)");
        row3.addView(durEdit, weight());
        root.addView(row3);

        speedupCheck = new CheckBox(this);
        speedupCheck.setText("保持帧率、压缩时长（快放）");
        speedupCheck.setOnCheckedChangeListener((v, c) -> scheduleEstimate());
        root.addView(speedupCheck);

        estLabel = new TextView(this);
        estLabel.setText("预估：—");
        estLabel.setGravity(Gravity.CENTER);
        root.addView(estLabel);

        genBtn = new Button(this);
        genBtn.setText("生成 .face");
        genBtn.setOnClickListener(v -> generate());
        root.addView(genBtn);

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        root.addView(progress);

        status = new TextView(this);
        status.setText("就绪");
        status.setGravity(Gravity.CENTER);
        root.addView(status);

        setContentView(root);
    }

    private Spinner spinner(String[] items, int def) {
        Spinner s = new Spinner(this);
        ArrayAdapter<String> a = new ArrayAdapter<>(this,
            android.R.layout.simple_spinner_item, items);
        a.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        s.setAdapter(a);
        s.setSelection(def);
        s.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                scheduleEstimate();
            }
            @Override public void onNothingSelected(AdapterView<?> p) {}
        });
        return s;
    }

    private EditText numEdit(String hint) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        e.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) {}
            @Override public void onTextChanged(CharSequence s, int a, int b, int c) {
                scheduleEstimate();
            }
            @Override public void afterTextChanged(Editable s) {}
        });
        return e;
    }

    private LinearLayout.LayoutParams weight() {
        return new LinearLayout.LayoutParams(0, dp(46), 1f);
    }

    private void pickFile() {
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.setType("*/*");
        i.addCategory(Intent.CATEGORY_OPENABLE);
        startActivityForResult(i, REQ_PICK);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_PICK && res == RESULT_OK && data != null && data.getData() != null) {
            sourceUri = data.getData();
            String mime = getContentResolver().getType(sourceUri);
            srcType = mime != null && mime.startsWith("image/") ? "image" : "video";
            fileLabel.setText(sourceUri.getLastPathSegment());
            new Thread(() -> {
                double dur = 0;
                if (!"image".equals(srcType)) {
                    dur = FaceGenerator.probeDurationMs(this, sourceUri, srcType);
                }
                final double durF = dur;
                android.graphics.Bitmap bmp = FaceGenerator.previewFrame(this, sourceUri, srcType);
                ui.post(() -> {
                    srcDurationMs = durF;
                    cropView.setBitmap(bmp);
                    if (durF > 0) {
                        fileLabel.setText(sourceUri.getLastPathSegment()
                            + String.format(Locale.US, "\n时长 %.1fs", durF / 1000.0));
                    }
                    updateEstimate();
                });
            }).start();
        }
    }

    // ---- 参数取值 ----
    private String levelOf(int pos) {
        return LEVEL_KEYS[Math.max(0, Math.min(pos, LEVEL_KEYS.length - 1))];
    }

    private int fpsOf(int pos) {
        return FPS_VALUES[Math.max(0, Math.min(pos, FPS_VALUES.length - 1))];
    }

    private int maxFrameOf(int pos) {
        return MAXFRAME_VALUES[Math.max(0, Math.min(pos, MAXFRAME_VALUES.length - 1))];
    }

    private String fmtOf() {
        return fmtSpinner.getSelectedItemPosition() == 1 ? "jpg" : "png";
    }

    private int jpgQualityOf() {
        int pos = Math.max(0, Math.min(jpgQSpinner.getSelectedItemPosition(),
            FaceGenerator.JPG_QUALITY_OPTIONS.length - 1));
        return FaceGenerator.JPG_QUALITY_OPTIONS[pos];
    }

    private double parseDouble(String s, double def) {
        if (s == null || s.trim().isEmpty()) return def;
        try { return Double.parseDouble(s.trim()); } catch (Exception e) { return def; }
    }

    private void scheduleEstimate() {
        ui.removeCallbacks(estRunner);
        ui.postDelayed(estRunner, 250);
    }

    private void updateEstimate() {
        if (sourceUri == null) {
            estLabel.setText("预估：—");
            return;
        }
        final Uri u = sourceUri;
        final String t = srcType;
        final int[] crop = cropView.getCrop();
        final String level = levelOf(levelSpinner.getSelectedItemPosition());
        final String fmt = fmtOf();
        final int jpgQ = jpgQualityOf();
        final int fps = fpsOf(fpsSpinner.getSelectedItemPosition());
        final int maxFrames = maxFrameOf(maxFrameSpinner.getSelectedItemPosition());
        final double cs = parseDouble(startEdit.getText().toString(), 0);
        final double cd = parseDouble(durEdit.getText().toString(), 0);
        final boolean speedup = speedupCheck.isChecked();
        final double dur = srcDurationMs;
        new Thread(() -> {
            FaceGenerator.Plan p = FaceGenerator.planFrames(dur, fps, cs, cd, maxFrames, speedup);
            long bytes = FaceGenerator.estimateBytes(
                MainActivity.this, u, t, crop, level, fmt, p.nFrames, jpgQ);
            ui.post(() -> {
                String extra = p.speedMult() > 1.01
                    ? String.format(Locale.US, " · %.1fx 快放 / 播放 %.1fs", p.speedMult(), p.playSeconds())
                    : String.format(Locale.US, " · 播放 %.1fs", p.playSeconds());
                String fmtTxt = "png".equals(fmt) ? "" : String.format(Locale.US, " · JPEG q%d", jpgQ);
                estLabel.setText(String.format(Locale.US,
                    "预计 %d 帧 @ %.1ffps · 约 %.2f MB%s%s",
                    p.nFrames, p.playFps, bytes / 1048576.0, fmtTxt, extra));
            });
        }).start();
    }

    private void generate() {
        if (sourceUri == null) { toast("请先选择素材"); return; }
        final int[] crop = cropView.getCrop();
        final int fps = fpsOf(fpsSpinner.getSelectedItemPosition());
        final String level = levelOf(levelSpinner.getSelectedItemPosition());
        final String fmt = fmtOf();
        final int jpgQ = jpgQualityOf();
        final int maxFrames = maxFrameOf(maxFrameSpinner.getSelectedItemPosition());
        final double clipStart = parseDouble(startEdit.getText().toString(), 0);
        final double clipDur = parseDouble(durEdit.getText().toString(), 0);
        final boolean speedup = speedupCheck.isChecked();

        genBtn.setEnabled(false);
        progress.setProgress(0);
        status.setText("生成中…");

        new Thread(() -> {
            try {
                String title = "Watchface";
                String faceId = String.valueOf(System.currentTimeMillis() / 1000).substring(0, 8);
                byte[] face = FaceGenerator.generate(MainActivity.this, sourceUri, srcType, crop,
                    level, fps, clipStart, clipDur, maxFrames, fmt, jpgQ, speedup, title, faceId,
                    (f, m) -> ui.post(() -> {
                        progress.setProgress((int) (f * 100));
                        status.setText(m);
                    }));

                String path = saveFace(face, faceId);
                final double mb = face.length / 1048576.0;
                ui.post(() -> {
                    genBtn.setEnabled(true);
                    progress.setProgress(100);
                    status.setText(String.format(Locale.US, "完成 %.2f MB\n%s", mb, path));
                    toast(String.format(Locale.US, "生成完成 %.2f MB", mb));
                });
            } catch (Exception e) {
                ui.post(() -> {
                    genBtn.setEnabled(true);
                    status.setText("失败: " + e.getMessage());
                    toast("生成失败: " + e.getMessage());
                });
            }
        }).start();
    }

    private String saveFace(byte[] face, String faceId) throws Exception {
        File dir = new File(getExternalFilesDir(null), "faces");
        dir.mkdirs();
        File f = new File(dir, "watchface_" + faceId + ".face");
        FileOutputStream out = new FileOutputStream(f);
        out.write(face);
        out.close();
        return f.getAbsolutePath();
    }

    private void toast(String m) { Toast.makeText(this, m, Toast.LENGTH_SHORT).show(); }

    private int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density); }
}
