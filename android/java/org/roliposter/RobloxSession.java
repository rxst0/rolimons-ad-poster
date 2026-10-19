package org.roliposter;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.webkit.CookieManager;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * "Read my trades directly" (opt-in): a copy of the Roblox sign-in (.ROBLOSECURITY) taken from the
 * trades tab's WebView, so RobloxApi can read trades without the page, including from the background
 * service (a separate process, which can't see the WebView's cookies).
 *
 * The copy is encrypted with an Android Keystore key that never leaves the phone. Only this package
 * can read it: get() is package-private, so the Python side can't. When the option is off nothing is
 * captured, and turning it off deletes the copy (clear()).
 */
public class RobloxSession {
    static final String COOKIE = ".ROBLOSECURITY";
    static final String ROBLOX_URL = "https://www.roblox.com";
    private static final String KEY_ALIAS = "roliposter_roblox_session";
    private static final String FILE = "roblox_session.bin";
    // A newer cookie Roblox sent to RobloxApi, waiting to be copied back into the WebView (main process).
    private static final String ROTATED_FILE = "roblox_session_rotated.bin";

    private static volatile boolean captureEnabled = false;

    /** Main process: whether pages finishing in the trades tab should copy the sign-in. */
    public static void setCaptureEnabled(boolean enabled) {
        captureEnabled = enabled;
    }

    public static boolean isCaptureEnabled() {
        return captureEnabled;
    }

    public static boolean isSignedIn(Context context) {
        return file(context, FILE).exists();
    }

    /**
     * Main process, UI thread: first copies a cookie Roblox rotated (see RobloxApi) back into the WebView,
     * then stores the WebView's current sign-in, or deletes the copy if it's signed out.
     */
    public static synchronized void captureFromWebView(Context context) {
        if (!captureEnabled) return;
        CookieManager cookies = CookieManager.getInstance();
        String rotated = read(context, ROTATED_FILE);
        if (rotated != null) {
            cookies.setCookie(ROBLOX_URL, rotated);
            cookies.flush();
            file(context, ROTATED_FILE).delete();
        }
        String value = cookieValue(cookies.getCookie(ROBLOX_URL));
        if (value == null) {
            clear(context);
        } else if (!value.equals(get(context))) {
            write(context, FILE, value);
        }
    }

    /** Deletes the stored copy (option turned off, or signed out of Roblox). */
    public static synchronized void clear(Context context) {
        file(context, FILE).delete();
        file(context, ROTATED_FILE).delete();
    }

    static synchronized String get(Context context) {
        return read(context, FILE);
    }

    /** Roblox replaced the cookie in a reply (Set-Cookie header): keep using the new one everywhere. */
    static synchronized void rotated(Context context, String setCookieHeader) {
        String value = cookieValue(setCookieHeader.split(";", 2)[0]);
        if (value == null || value.equals(get(context))) return;
        write(context, FILE, value);
        write(context, ROTATED_FILE, setCookieHeader);
    }

    /** The .ROBLOSECURITY value in a "name=value; name=value" cookie string, or null. */
    static String cookieValue(String header) {
        if (header == null) return null;
        for (String part : header.split(";")) {
            String p = part.trim();
            if (p.startsWith(COOKIE + "=")) {
                String value = p.substring(COOKIE.length() + 1);
                return value.isEmpty() ? null : value;
            }
        }
        return null;
    }

    // ---- encrypted storage ----------------------------------------------------------------
    private static File file(Context context, String name) {
        return new File(context.getApplicationContext().getFilesDir(), name);
    }

    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY_ALIAS, null);
    }

    private static void write(Context context, String name, String text) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] iv = cipher.getIV();
            byte[] data = cipher.doFinal(text.getBytes(StandardCharsets.UTF_8));
            File target = file(context, name);
            File tmp = new File(target.getPath() + ".tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(iv.length);
                out.write(iv);
                out.write(data);
            }
            if (!tmp.renameTo(target)) tmp.delete();
        } catch (Exception e) {
            file(context, name).delete();
        }
    }

    private static String read(Context context, String name) {
        File source = file(context, name);
        if (!source.exists()) return null;
        try {
            byte[] raw = Files.readAllBytes(source.toPath());
            int ivLength = raw[0];
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, raw, 1, ivLength));
            byte[] text = cipher.doFinal(raw, 1 + ivLength, raw.length - 1 - ivLength);
            return new String(text, StandardCharsets.UTF_8);
        } catch (Exception e) {
            source.delete();  // unreadable (for example the key was reset): sign in again
            return null;
        }
    }
}
