import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}
if (file("google-services.json").exists()) { apply(plugin = "com.google.gms.google-services") }
val releaseSigning = providers.environmentVariable("LOSANGELEX_SIGNING_PROPERTIES").orNull?.let { path ->
    Properties().apply { file(path).inputStream().use(::load) }
}
android {
    namespace = "co.fallsoft.losangelex"
    compileSdk = 37
    defaultConfig {
        applicationId = "co.fallsoft.losangelex"
        minSdk = 26
        targetSdk = 36
        versionCode = 3
        versionName = "0.2.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions { unitTests.isReturnDefaultValues = true }
    if (releaseSigning != null) {
        signingConfigs.create("privateRelease") {
            storeFile = file(releaseSigning.getProperty("storeFile"))
            storePassword = releaseSigning.getProperty("storePassword")
            keyAlias = releaseSigning.getProperty("keyAlias")
            keyPassword = releaseSigning.getProperty("keyPassword")
        }
        buildTypes.getByName("release") { signingConfig = signingConfigs.getByName("privateRelease") }
    }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
dependencies {
    constraints {
        implementation("androidx.fragment:fragment:1.8.9") {
            because("Play services otherwise selects Fragment 1.1, incompatible with Activity Result APIs")
        }
    }
    implementation(platform("androidx.compose:compose-bom:2026.08.00"))
    implementation("androidx.activity:activity-compose:1.12.4")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.paging:paging-compose:3.5.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation(platform("com.google.firebase:firebase-bom:34.19.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("com.google.firebase:firebase-installations")
    androidTestImplementation(platform("androidx.compose:compose-bom:2026.08.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test:runner:1.7.0")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
