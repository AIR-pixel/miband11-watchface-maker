package face.tool

import android.content.Context
import android.content.res.Configuration

/**
 * Material You（Monet）动态配色 —— **纯 framework 实现，不引任何库**。
 *
 * 取色顺序：
 *  1. 系统动态色：Android 12（API 31）起系统把壁纸提取出的调色板做成 framework 资源
 *     `@android:color/system_accent1_600` 这一族，任何 App 都能直接读。
 *     这就是"自适应手机主题"的原生入口，不需要 Material Components / AndroidX。
 *  2. 取不到（API < 31，或厂商 ROM 没提供）→ 整套退回 M3 baseline（固定蓝 #0B57D0 系）。
 *
 * 深浅由两件事决定：本 App 里的覆盖（跟随系统 / 浅色 / 深色）+ 系统夜间模式。
 *
 * 两个必须记住的点：
 * - **资源名是按名字查的，不是按 `android.R.color.*` 常量**。常量在 API 31 才存在，
 *   直接写死会让低版本机型上 `getColor()` 抛 NotFoundException；用
 *   `getIdentifier(name, "color", "android")` 查不到返回 0，零崩溃风险。
 * - **Monet 档位索引 = 色调 tone × 10 反过来**：`0`=tone100（近白），`1000`=tone0（近黑）。
 *   所以浅色主题取 `*_600`（tone40）作主色，深色主题取 `*_200`（tone80）——
 *   这是 Google 自己的映射，别自己拍脑袋换档位，对比度会崩。
 */
class Palette private constructor(
    val night: Boolean,
    /** 是否真的用上了系统动态色（false = 走的 baseline）。 */
    val monet: Boolean,

    val primary: Int,
    val onPrimary: Int,
    val primaryContainer: Int,
    val onPrimaryContainer: Int,

    val secondary: Int,
    val onSecondary: Int,
    val secondaryContainer: Int,
    val onSecondaryContainer: Int,

    val surface: Int,
    val onSurface: Int,
    val surfaceContainerLow: Int,
    val surfaceContainer: Int,
    val surfaceContainerHigh: Int,
    val surfaceContainerHighest: Int,

    val surfaceVariant: Int,
    val onSurfaceVariant: Int,
    val outline: Int,
    val outlineVariant: Int,

    val error: Int,
    val onError: Int
) {

    companion object {

        fun of(ctx: Context): Palette = build(ctx, ThemeMode.isNight(ctx))

        private fun build(ctx: Context, night: Boolean): Palette {
            // 探测一档就够：系统要么整套提供，要么整套没有，不会半套。
            val probe = sys(ctx, "system_accent1_600")
            val monet = probe != null

            // 主色组 accent1
            val primary = probe ?: fb(night, 0xFF0B57D0, 0xFFADC6FF)
            val onPrimary = m(ctx, monet, "accent1", 0, night, 0xFFFFFFFF, 0xFF002E69)
            val primaryContainer = m(ctx, monet, "accent1", 100, night, 0xFFD8E2FF, 0xFF284E91)
            val onPrimaryContainer = m(ctx, monet, "accent1", 900, night, 0xFF001A41, 0xFFD8E2FF)

            // 次色组 accent2（tonal 按钮用）
            val secondary = m(ctx, monet, "accent2", 600, night, 0xFF535F70, 0xFFBBC7DB)
            val onSecondary = m(ctx, monet, "accent2", 0, night, 0xFFFFFFFF, 0xFF233141)
            val secondaryContainer = m(ctx, monet, "accent2", 100, night, 0xFFD7E3F7, 0xFF3A4858)
            val onSecondaryContainer = m(ctx, monet, "accent2", 900, night, 0xFF101C2B, 0xFFD7E3F7)

            // 中性组 neutral1：背景与卡片
            val surface = m(ctx, monet, "neutral1", 10, night, 0xFFF8F9FC, 0xFF101317)
            val onSurface = m(ctx, monet, "neutral1", 900, night, 0xFF191C1E, 0xFFE1E2E7)
            val surfaceContainerLow = m(ctx, monet, "neutral1", 50, night, 0xFFF3F4F8, 0xFF191C21)
            val container = m(ctx, monet, "neutral1", 100, night, 0xFFEDEFF4, 0xFF1E2126)
            val containerHigh = m(ctx, monet, "neutral1", 200, night, 0xFFE7E9EF, 0xFF282B31)
            val containerHighest = m(ctx, monet, "neutral1", 200, night, 0xFFE1E3E9, 0xFF33363D)

            // 中性变体 neutral2：次要文字、描边
            val surfaceVariant = m(ctx, monet, "neutral2", 50, night, 0xFFDFE2EB, 0xFF42474E)
            val onSurfaceVariant = m(ctx, monet, "neutral2", 700, night, 0xFF43474E, 0xFFC2C7CF)
            val outline = m(ctx, monet, "neutral2", 500, night, 0xFF73777F, 0xFF8C919A)
            val outlineVariant = m(ctx, monet, "neutral2", 200, night, 0xFFC3C7CF, 0xFF42474E)

            return Palette(
                night = night, monet = monet,
                primary = primary, onPrimary = onPrimary,
                primaryContainer = primaryContainer, onPrimaryContainer = onPrimaryContainer,
                secondary = secondary, onSecondary = onSecondary,
                secondaryContainer = secondaryContainer, onSecondaryContainer = onSecondaryContainer,
                surface = surface, onSurface = onSurface,
                surfaceContainerLow = surfaceContainerLow,
                surfaceContainer = container,
                surfaceContainerHigh = containerHigh,
                surfaceContainerHighest = containerHighest,
                surfaceVariant = surfaceVariant, onSurfaceVariant = onSurfaceVariant,
                outline = outline, outlineVariant = outlineVariant,
                error = fb(night, 0xFFB3261E, 0xFFF2B8B5),
                onError = fb(night, 0xFFFFFFFF, 0xFF601410)
            )
        }

        /** 读一档系统动态色；查不到返回 null（不是抛异常）。 */
        private fun sys(ctx: Context, name: String): Int? {
            val id = ctx.resources.getIdentifier(name, "color", "android")
            if (id == 0) return null
            return try {
                ctx.getColor(id)          // API 23+；minSdk 24，安全
            } catch (t: Throwable) {
                null
            }
        }

        // 色值写成 0xFFRRGGBB 会被推断成 Long（超过 Int 正区间），
        // 所以这两个 fallback 参数收 Long，末尾统一 .toInt() 转回 ARGB int。
        private fun m(ctx: Context, monet: Boolean, group: String, idx: Int,
                      night: Boolean, lightFb: Long, darkFb: Long): Int {
            if (!monet) return fb(night, lightFb, darkFb)
            return sys(ctx, "system_${group}_$idx") ?: fb(night, lightFb, darkFb)
        }

        private fun fb(night: Boolean, light: Long, dark: Long) =
            (if (night) dark else light).toInt()
    }
}

/**
 * 主题覆盖：跟随系统 / 强制浅色 / 强制深色。
 *
 * 注意**没有**用 `UiModeManager.setNightMode()` —— 那需要系统级权限
 * `CHANGE_CONFIGURATION`，普通 App 拿不到。这里只改本 App 自己的配色，
 * 写进 SharedPreferences 后 `recreate()` 重建界面即可，不影响系统。
 */
object ThemeMode {
    const val FOLLOW = 0
    const val LIGHT = 1
    const val DARK = 2

    private const val PREF = "ui_theme"
    private const val KEY = "mode"

    fun get(ctx: Context): Int =
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).getInt(KEY, FOLLOW)

    fun set(ctx: Context, mode: Int) =
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit().putInt(KEY, mode).apply()

    fun isNight(ctx: Context): Boolean = when (get(ctx)) {
        LIGHT -> false
        DARK -> true
        else -> (ctx.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
            Configuration.UI_MODE_NIGHT_YES
    }

    fun label(ctx: Context): String = when (get(ctx)) {
        LIGHT -> "浅色"
        DARK -> "深色"
        else -> "跟随系统"
    }

    /** 点一下切到下一档，返回新档位。 */
    fun next(ctx: Context): Int {
        val n = (get(ctx) + 1) % 3
        set(ctx, n)
        return n
    }
}
