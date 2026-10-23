package br.com.consultapix;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.net.ssl.SSLException;

public final class MainActivity extends Activity {
    private static final int BG = Color.rgb(243, 246, 245);
    private static final int INK = Color.rgb(24, 60, 53);
    private static final int MUTED = Color.rgb(82, 109, 102);
    private static final int GREEN = Color.rgb(24, 113, 90);
    private static final int SOFT_GREEN = Color.rgb(237, 247, 239);
    private static final String ENDPOINT = "https://api.asaas.com/v3/pix/addressKeys/external";
    private static final int PICK_LIST = 41;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler clock = new Handler(Looper.getMainLooper());
    private EditText tokenInput, keyInput;
    private Spinner typeInput;
    private Button saveButton, queryButton, manualButton, listButton, importButton, selectLineButton;
    private TextView status, cooldown, resultText;
    private LinearLayout resultBox;
    private LinearLayout listControls;
    private TextView listSummary, selectedLine;
    private ProgressBar progress;
    private TokenStore tokenStore;
    private List<Long> queryHistory = new ArrayList<>();
    private boolean busy, importing, listMode, historyAvailable = true;
    private ListImporter.Result importedList;
    private int selectedIndex = -1;
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (isFinishing() || isDestroyed()) return;
            updateButton();
            clock.postDelayed(this, 500L);
        }
    };

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        tokenStore = new TokenStore(this);
        buildUi();
        try {
            queryHistory = tokenStore.loadHistory();
            String token = tokenStore.load();
            if (!token.isEmpty()) {
                tokenInput.setText(token);
                status.setText("Token salvo carregado. Pronto para consultar.");
            }
        } catch (Exception ignored) {
            historyAvailable = false;
            status.setText("Não foi possível ler o cache. Reinicie o aplicativo para tentar novamente.");
        }
        clock.post(tick);
    }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private GradientDrawable background(int color, int border) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(10));
        if (border != 0) drawable.setStroke(dp(1), border);
        return drawable;
    }

    private LinearLayout.LayoutParams rowParams(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(top);
        return params;
    }

    private EditText entry(boolean password) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true);
        edit.setTextSize(16);
        edit.setTextColor(INK);
        edit.setPadding(dp(12), dp(12), dp(12), dp(12));
        edit.setBackground(background(Color.WHITE, Color.rgb(170, 188, 181)));
        edit.setSaveEnabled(false);
        edit.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        if (password) {
            edit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            edit.setTransformationMethod(PasswordTransformationMethod.getInstance());
        }
        return edit;
    }

    private Button button(String title, boolean primary) {
        Button button = new Button(this);
        button.setText(title);
        button.setAllCaps(false);
        button.setTextSize(16);
        button.setMinHeight(dp(48));
        button.setTextColor(primary ? Color.WHITE : GREEN);
        button.setBackground(background(primary ? GREEN : Color.rgb(226, 236, 231), 0));
        button.setPadding(dp(14), dp(8), dp(14), dp(8));
        return button;
    }

    private void buildUi() {
        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.setBackgroundColor(BG);
        outer.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        outer.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(22), dp(24), dp(22), dp(22));
        scroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        body.addView(text("Consultar Pix", 28, INK, true));
        body.addView(text("Uma chave por vez", 14, MUTED, false), rowParams(5));

        LinearLayout tokenLabelRow = new LinearLayout(this);
        tokenLabelRow.setGravity(Gravity.CENTER_VERTICAL);
        tokenLabelRow.addView(text("Token", 15, INK, true), new LinearLayout.LayoutParams(0, -2, 1));
        CheckBox show = new CheckBox(this);
        show.setText("Mostrar");
        show.setTextSize(13);
        show.setTextColor(MUTED);
        tokenLabelRow.addView(show);
        body.addView(tokenLabelRow, rowParams(24));
        LinearLayout tokenRow = new LinearLayout(this);
        tokenRow.setGravity(Gravity.CENTER_VERTICAL);
        tokenInput = entry(true);
        tokenInput.setHint("Cole seu token de produção");
        tokenRow.addView(tokenInput, new LinearLayout.LayoutParams(0, -2, 1));
        saveButton = button("Salvar", false);
        LinearLayout.LayoutParams saveParams = new LinearLayout.LayoutParams(-2, dp(48));
        saveParams.leftMargin = dp(8);
        tokenRow.addView(saveButton, saveParams);
        body.addView(tokenRow, rowParams(2));
        body.addView(text("Salvar lembra o token neste aparelho.", 12, MUTED, false), rowParams(6));
        show.setOnCheckedChangeListener((button, checked) -> {
            tokenInput.setTransformationMethod(checked ? null : PasswordTransformationMethod.getInstance());
            tokenInput.setSelection(tokenInput.getText().length());
        });
        saveButton.setOnClickListener(view -> saveToken());

        LinearLayout modes = new LinearLayout(this);
        manualButton = button("Manual", true);
        listButton = button("Lista", false);
        modes.addView(manualButton, new LinearLayout.LayoutParams(0, dp(46), 1));
        LinearLayout.LayoutParams listModeParams = new LinearLayout.LayoutParams(0, dp(46), 1);
        listModeParams.leftMargin = dp(8);
        modes.addView(listButton, listModeParams);
        body.addView(modes, rowParams(22));
        manualButton.setOnClickListener(view -> switchMode(false));
        listButton.setOnClickListener(view -> switchMode(true));
        listControls = new LinearLayout(this);
        listControls.setOrientation(LinearLayout.VERTICAL);
        listControls.setVisibility(View.GONE);
        importButton = button("Importar TXT", false);
        importButton.setOnClickListener(view -> pickList());
        listControls.addView(importButton, rowParams(12));
        listSummary = text("Importe um arquivo para identificar 11 dígitos por linha.", 13, MUTED, false);
        listControls.addView(listSummary, rowParams(8));
        selectLineButton = button("Selecionar linha", false);
        selectLineButton.setEnabled(false);
        selectLineButton.setOnClickListener(view -> chooseLine());
        listControls.addView(selectLineButton, rowParams(10));
        selectedLine = text("Nenhuma linha selecionada.", 13, MUTED, false);
        listControls.addView(selectedLine, rowParams(8));
        listControls.addView(text("Importar ou selecionar não consulta. Confira CPF ou Telefone no campo Tipo e toque em Consultar.", 12, MUTED, false), rowParams(6));
        body.addView(listControls, rowParams(0));

        body.addView(text("Tipo de chave", 15, INK, true), rowParams(23));
        typeInput = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, PixCore.TYPE_LABELS);
        typeInput.setAdapter(adapter);
        typeInput.setBackground(background(Color.WHITE, Color.rgb(170, 188, 181)));
        typeInput.setMinimumHeight(dp(48));
        typeInput.setPadding(dp(8), 0, dp(8), 0);
        body.addView(typeInput, rowParams(7));
        body.addView(text("Chave Pix", 15, INK, true), rowParams(17));
        keyInput = entry(false);
        keyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        keyInput.setHint("Digite a chave que deseja consultar");
        keyInput.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        body.addView(keyInput, rowParams(7));
        queryButton = button("Consultar", true);
        body.addView(queryButton, rowParams(20));
        queryButton.setOnClickListener(view -> query());
        keyInput.setOnEditorActionListener((view, action, event) -> {
            if (action == EditorInfo.IME_ACTION_SEARCH) { query(); return true; }
            return false;
        });
        cooldown = text("Uma consulta a cada 61 segundos.", 12, MUTED, false);
        body.addView(cooldown, rowParams(8));
        status = text("Pronto para consultar.", 13, MUTED, false);
        body.addView(status, rowParams(12));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true);
        progress.setVisibility(View.GONE);
        body.addView(progress, rowParams(8));
        body.addView(text("Resultado", 16, INK, true), rowParams(23));
        resultBox = new LinearLayout(this);
        resultBox.setOrientation(LinearLayout.VERTICAL);
        resultBox.setPadding(dp(16), dp(16), dp(16), dp(16));
        resultBox.setBackground(background(Color.WHITE, Color.rgb(206, 218, 212)));
        resultText = text("O retorno da consulta aparecerá aqui.", 15, INK, false);
        resultText.setTextIsSelectable(true);
        resultText.setMinHeight(dp(130));
        resultBox.addView(resultText, new LinearLayout.LayoutParams(-1, -2));
        body.addView(resultBox, rowParams(9));
        body.addView(text("Somente consulta. Nenhuma transferência é realizada.", 12, MUTED, false), rowParams(18));
        setContentView(outer);
        outer.requestApplyInsets();
    }

    private void switchMode(boolean useList) {
        if (busy || importing) return;
        listMode = useList;
        listControls.setVisibility(useList ? View.VISIBLE : View.GONE);
        keyInput.setEnabled(!useList);
        manualButton.setBackground(background(useList ? Color.rgb(226, 236, 231) : GREEN, 0));
        manualButton.setTextColor(useList ? GREEN : Color.WHITE);
        listButton.setBackground(background(useList ? GREEN : Color.rgb(226, 236, 231), 0));
        listButton.setTextColor(useList ? Color.WHITE : GREEN);
        if (useList && importedList != null && selectedIndex >= 0)
            keyInput.setText(importedList.items.get(selectedIndex).digits);
        updateButton();
    }

    private void pickList() {
        if (busy || importing) return;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"text/plain", "application/octet-stream"});
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try { startActivityForResult(intent, PICK_LIST); }
        catch (Exception unavailable) { status.setText("Não foi possível abrir o seletor de arquivos deste aparelho."); }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_LIST || result != RESULT_OK || data == null || data.getData() == null) return;
        if (busy || importing) return;
        Uri uri = data.getData();
        setImporting(true);
        status.setText("Lendo arquivo local… Nenhuma consulta será enviada.");
        status.setTextColor(MUTED);
        worker.execute(() -> {
            String name = "Arquivo importado";
            ListImporter.Result parsed = null;
            String failure = null;
            try {
                try (Cursor cursor = getContentResolver().query(uri,
                        new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst()) {
                        int nameColumn = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                        if (nameColumn >= 0 && !cursor.isNull(nameColumn)) name = cursor.getString(nameColumn);
                        int sizeColumn = cursor.getColumnIndex(OpenableColumns.SIZE);
                        if (sizeColumn >= 0 && !cursor.isNull(sizeColumn) && cursor.getLong(sizeColumn) > ListImporter.MAX_TEXT_BYTES)
                            throw new Exception("O arquivo TXT é maior que 8 MB. Divida-o em arquivos menores.");
                    }
                }
                name = name.replaceAll("[\\x00-\\x1f]", " ");
                if (name.length() > 180) name = name.substring(0, 180);
                byte[] bytes = readLocalFile(uri);
                String lower = name.toLowerCase(Locale.ROOT);
                if (!lower.endsWith(".txt")) throw new Exception("Selecione um arquivo de texto com extensão .txt.");
                String content = ListImporter.decode(bytes);
                parsed = ListImporter.parse(content);
                if (parsed.items.isEmpty()) throw new Exception("Nenhuma linha com um único número de 11 dígitos foi identificada. Linhas com mais de um candidato são ignoradas.");
            } catch (OutOfMemoryError tooLarge) {
                failure = "Não há memória suficiente para ler esse arquivo. Divida-o em arquivos menores.";
            } catch (Exception error) {
                failure = error.getMessage();
                if (failure == null || failure.trim().isEmpty()) failure = "Não foi possível ler o arquivo selecionado.";
                if (failure.length() > 400) failure = failure.substring(0, 400);
            }
            final ListImporter.Result list = parsed;
            final String filename = name;
            final String message = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                if (message == null && list != null) {
                    importedList = list;
                    selectedIndex = -1;
                    keyInput.setText("");
                    listSummary.setText(filename + "\n" + list.items.size() + " linhas com 11 dígitos identificados.\n"
                            + list.ambiguousLines + " linhas ambíguas ignoradas; " + list.ignoredLines + " sem candidato.");
                    selectedLine.setText("Selecione a linha que deseja consultar.");
                    status.setText("Arquivo importado. Selecione uma linha e toque em Consultar.");
                    status.setTextColor(GREEN);
                } else {
                    status.setText(message == null ? "Não foi possível importar o arquivo." : message);
                    status.setTextColor(Color.rgb(124, 79, 36));
                }
                setImporting(false);
            });
        });
    }

    private byte[] readLocalFile(Uri uri) throws Exception {
        try (InputStream input = getContentResolver().openInputStream(uri);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            if (input == null) throw new Exception("Não foi possível abrir o arquivo selecionado.");
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > ListImporter.MAX_TEXT_BYTES)
                    throw new Exception("O arquivo TXT é maior que 8 MB. Divida-o em arquivos menores.");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }

    private void chooseLine() {
        if (busy || importing || importedList == null || importedList.items.isEmpty()) return;
        String[] labels = new String[importedList.items.size()];
        for (int i = 0; i < labels.length; i++) labels[i] = importedList.items.get(i).label();
        new AlertDialog.Builder(this).setTitle("11 dígitos identificados")
                .setItems(labels, (dialog, index) -> {
                    selectedIndex = index;
                    ListImporter.Item item = importedList.items.get(index);
                    keyInput.setText(item.digits);
                    selectedLine.setText(item.label());
                    status.setText("Linha selecionada. Confira o tipo e toque em Consultar.");
                    status.setTextColor(MUTED);
                    updateButton();
                }).setNegativeButton("Fechar", null).show();
    }

    private void setImporting(boolean value) {
        importing = value;
        saveButton.setEnabled(!value);
        tokenInput.setEnabled(!value);
        keyInput.setEnabled(!value && !listMode);
        typeInput.setEnabled(!value);
        manualButton.setEnabled(!value);
        listButton.setEnabled(!value);
        importButton.setEnabled(!value);
        selectLineButton.setEnabled(!value && importedList != null && !importedList.items.isEmpty());
        progress.setVisibility(value ? View.VISIBLE : View.GONE);
        updateButton();
    }

    private void saveToken() {
        if (busy || importing) return;
        String value = tokenInput.getText().toString().trim();
        try {
            if (!value.isEmpty()) value = PixCore.normalizeToken(value);
            tokenStore.save(value);
            if (!historyAvailable) {
                queryHistory = tokenStore.loadHistory();
                historyAvailable = true;
            }
            status.setText(value.isEmpty() ? "Token salvo removido." : "Token salvo neste aparelho.");
            status.setTextColor(GREEN);
        } catch (PixCore.InputError error) {
            status.setText(error.getMessage());
            status.setTextColor(Color.rgb(153, 63, 42));
        } catch (Exception ignored) {
            status.setText("Não foi possível salvar o token ou acessar o cache neste aparelho.");
            status.setTextColor(Color.rgb(153, 63, 42));
        }
        updateButton();
    }

    private void updateButton() {
        if (busy || importing) {
            queryButton.setEnabled(false);
            queryButton.setText(importing ? "Importando…" : "Consultando…");
            return;
        }
        long remaining = PixCore.waitMillis(queryHistory, System.currentTimeMillis());
        boolean selected = !listMode || (importedList != null && selectedIndex >= 0 && selectedIndex < importedList.items.size());
        boolean available = historyAvailable && remaining == 0L && selected;
        queryButton.setEnabled(available);
        queryButton.setAlpha(available ? 1f : 0.6f);
        queryButton.setText(!historyAvailable ? "Cache indisponível" : remaining > 0L ? "Aguarde " + PixCore.countdown(remaining) : "Consultar");
        cooldown.setText(remaining > 0L ? "Próxima consulta em " + PixCore.countdown(remaining) + "." : "Uma consulta a cada 61 segundos.");
    }

    private void setBusy(boolean value) {
        busy = value;
        saveButton.setEnabled(!value);
        tokenInput.setEnabled(!value);
        keyInput.setEnabled(!value && !listMode);
        typeInput.setEnabled(!value);
        manualButton.setEnabled(!value);
        listButton.setEnabled(!value);
        importButton.setEnabled(!value);
        selectLineButton.setEnabled(!value && importedList != null && !importedList.items.isEmpty());
        progress.setVisibility(value ? View.VISIBLE : View.GONE);
        updateButton();
    }

    private void query() {
        if (busy || importing || !historyAvailable) return;
        if (listMode && (importedList == null || selectedIndex < 0 || selectedIndex >= importedList.items.size())) {
            status.setText("Selecione uma linha da lista antes de consultar.");
            return;
        }
        final String token, key, type;
        try {
            token = PixCore.normalizeToken(tokenInput.getText().toString());
            type = PixCore.TYPES[typeInput.getSelectedItemPosition()];
            key = PixCore.normalizeKey(type, listMode ? importedList.items.get(selectedIndex).digits : keyInput.getText().toString());
        } catch (PixCore.InputError error) {
            status.setText(error.getMessage());
            status.setTextColor(Color.rgb(153, 63, 42));
            return;
        }
        try {
            long now = System.currentTimeMillis();
            queryHistory = tokenStore.loadHistory();
            if (PixCore.waitMillis(queryHistory, now) > 0L) { updateButton(); return; }
            queryHistory = PixCore.recentQueries(queryHistory, now);
            queryHistory.add(now);
            tokenStore.saveHistory(queryHistory);
        } catch (Exception ignored) {
            historyAvailable = false;
            status.setText("Não foi possível registrar a consulta no cache. Nenhuma consulta foi enviada.");
            status.setTextColor(Color.rgb(153, 63, 42));
            updateButton();
            return;
        }
        InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(keyInput.getWindowToken(), 0);
        setBusy(true);
        status.setText("Consultando…");
        status.setTextColor(MUTED);
        resultText.setText("Consultando a chave informada…");
        resultText.setTextColor(INK);
        resultBox.setBackground(background(Color.WHITE, Color.rgb(206, 218, 212)));
        worker.execute(() -> {
            ApiResult result = fetch(token, type, key);
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                setBusy(false);
                if (listMode && importedList != null && selectedIndex >= 0 && selectedIndex < importedList.items.size()) {
                    ListImporter.Item item = importedList.items.get(selectedIndex);
                    item.state = result.kind == 0 ? "Chave cadastrada" : result.kind == 1 ? "Sem Pix cadastrado" : "Consulta não concluída";
                    selectedLine.setText(item.label());
                }
                resultText.setText(PixCore.sanitize(result.message, token));
                if (result.kind == 1) {
                    resultBox.setBackground(background(SOFT_GREEN, Color.rgb(182, 216, 194)));
                    resultText.setTextColor(Color.rgb(77, 130, 104));
                    status.setText("Consulta concluída: chave não cadastrada.");
                    status.setTextColor(Color.rgb(77, 130, 104));
                } else if (result.kind == 0) {
                    resultBox.setBackground(background(Color.WHITE, Color.rgb(206, 218, 212)));
                    resultText.setTextColor(INK);
                    status.setText("Consulta concluída.");
                    status.setTextColor(GREEN);
                } else {
                    resultBox.setBackground(background(Color.rgb(255, 247, 235), Color.rgb(226, 210, 181)));
                    resultText.setTextColor(Color.rgb(124, 79, 36));
                    status.setText("Consulta não concluída. Veja o motivo abaixo.");
                    status.setTextColor(Color.rgb(124, 79, 36));
                }
            });
        });
    }

    private static final class ApiResult {
        final int kind;
        final String message;
        ApiResult(int kind, String message) { this.kind = kind; this.message = message; }
    }

    private ApiResult fetch(String token, String type, String key) {
        HttpURLConnection connection = null;
        try {
            String query = "?type=" + URLEncoder.encode(type, "UTF-8") + "&key=" + URLEncoder.encode(key, "UTF-8");
            connection = (HttpURLConnection) new URL(ENDPOINT + query).openConnection();
            connection.setRequestMethod("GET");
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(20000);
            connection.setReadTimeout(20000);
            connection.setRequestProperty("access_token", token);
            connection.setRequestProperty("User-Agent", "ConsultaPixAndroid/1.6");
            connection.setRequestProperty("Accept", "application/json");
            int http = connection.getResponseCode();
            InputStream stream = http >= 400 ? connection.getErrorStream() : connection.getInputStream();
            String body = readBody(stream);
            JSONObject data = null;
            try { data = new JSONObject(body); } catch (JSONException ignored) { }
            List<PixCore.ApiError> errors = errors(data);
            if (http >= 200 && http < 300 && data != null && data.length() > 0 && errors.isEmpty())
                return new ApiResult(0, format(data));
            if ((http == 400 || http == 404) && PixCore.isExplicitMissing(http, errors))
                return new ApiResult(1, PixCore.missingMessage(type) + "\n\nA resposta do serviço confirmou que esta chave não está cadastrada.\n\nHTTP " + http);
            if (http >= 200 && http < 300) {
                if (!errors.isEmpty()) return new ApiResult(2, PixCore.errorMessage(400, errors));
                return new ApiResult(2, "O serviço retornou uma resposta inesperada. Não foi possível confirmar a situação da chave.");
            }
            return new ApiResult(2, PixCore.errorMessage(http, errors));
        } catch (SocketTimeoutException error) {
            return new ApiResult(2, "A consulta demorou para responder. Confira a conexão e tente novamente.");
        } catch (SSLException error) {
            return new ApiResult(2, "Não foi possível validar a conexão segura. Confira a data e a conexão do aparelho.");
        } catch (Exception error) {
            return new ApiResult(2, "Não foi possível concluir a consulta. Confira sua internet e tente novamente.");
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String readBody(InputStream stream) throws Exception {
        if (stream == null) return "";
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > PixCore.MAX_RESPONSE) throw new Exception("Resposta grande demais.");
                output.write(buffer, 0, count);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private List<PixCore.ApiError> errors(JSONObject data) {
        List<PixCore.ApiError> list = new ArrayList<>();
        if (data == null) return list;
        JSONArray values = data.optJSONArray("errors");
        if (values != null) {
            for (int i = 0; i < Math.min(values.length(), 10); i++) {
                JSONObject error = values.optJSONObject(i);
                if (error != null) list.add(new PixCore.ApiError(error.optString("code", ""), error.optString("description", "")));
            }
        }
        if (list.isEmpty() && data.has("description"))
            list.add(new PixCore.ApiError(data.optString("code", ""), data.optString("description", "")));
        if (list.isEmpty() && data.has("message"))
            list.add(new PixCore.ApiError(data.optString("code", ""), data.optString("message", "")));
        return list;
    }

    private String format(JSONObject data) throws JSONException {
        StringBuilder result = new StringBuilder();
        JSONObject owner = data.optJSONObject("owner");
        JSONObject bank = data.optJSONObject("financialInstitution");
        append(result, "Titular", owner == null ? data.optString("ownerName", data.optString("name", "")) : owner.optString("name", ""));
        append(result, "CPF/CNPJ", owner == null ? data.optString("cpfCnpj", "") : owner.optString("cpfCnpj", ""));
        append(result, "Instituição", bank == null ? data.optString("ispbName", "") : bank.optString("name", ""));
        append(result, "Código do banco", bank == null ? "" : bank.optString("code", ""));
        append(result, "Chave", data.optString("key", ""));
        append(result, "Tipo", data.optString("type", ""));
        if (result.length() > 0) result.append("Resposta completa\n\n");
        return result.append(data.toString(2)).toString();
    }

    private void append(StringBuilder result, String label, String value) {
        if (!value.isEmpty() && !"null".equals(value)) result.append(label).append("\n").append(value).append("\n\n");
    }

    @Override protected void onDestroy() {
        clock.removeCallbacks(tick);
        worker.shutdownNow();
        super.onDestroy();
    }
}
