#include <AccelStepper.h>

// AZ motor
#define AZ_STEP   3
#define AZ_DIR    2
//#define AZ_SLEEP  4
#define AZ_MS1    7
#define AZ_MS2    6
#define AZ_MS3    5

// EL motor
#define EL_STEP   9
#define EL_DIR    8
//#define EL_SLEEP  10
#define EL_MS1    13
#define EL_MS2    12
#define EL_MS3    11

const float STEPS_PER_DEG = 8.888;
const float MAX_AZ_STEPS  = 360.0 * STEPS_PER_DEG;
const float EL_MIN_DEG    = 0.0;
const float EL_MAX_DEG    = 85.0;
const float MAX_SPEED     = 1000.0;
const float ACCELERATION  = 400.0;

AccelStepper azStepper(AccelStepper::DRIVER, AZ_STEP, AZ_DIR);
AccelStepper elStepper(AccelStepper::DRIVER, EL_STEP, EL_DIR);

void setup() {
    Serial.begin(115200);
    while (!Serial);
    delay(500);

    while (Serial.available()) Serial.read();
    Serial.println("READY");

    // Wake drivers
    //pinMode(AZ_SLEEP, OUTPUT); digitalWrite(AZ_SLEEP, HIGH);
    //pinMode(EL_SLEEP, OUTPUT); digitalWrite(EL_SLEEP, HIGH);

    // 1/16 microstepping
    pinMode(AZ_MS1, OUTPUT); pinMode(AZ_MS2, OUTPUT); pinMode(AZ_MS3, OUTPUT);
    pinMode(EL_MS1, OUTPUT); pinMode(EL_MS2, OUTPUT); pinMode(EL_MS3, OUTPUT);
    digitalWrite(AZ_MS1, HIGH); digitalWrite(AZ_MS2, HIGH); digitalWrite(AZ_MS3, HIGH);
    digitalWrite(EL_MS1, HIGH); digitalWrite(EL_MS2, HIGH); digitalWrite(EL_MS3, HIGH);

    // Stepper configs
    azStepper.setMaxSpeed(MAX_SPEED);
    azStepper.setAcceleration(ACCELERATION);

    elStepper.setMaxSpeed(MAX_SPEED);
    elStepper.setAcceleration(ACCELERATION);

    azStepper.setCurrentPosition(0);
    elStepper.setCurrentPosition(0);

    Serial.println("[Tracker] Ready.");
}

void loop() {

    if (Serial.available()) {

        char buf[32];
        int len = Serial.readBytesUntil('\n', buf, sizeof(buf)-1);
        if (len <= 0) return;
        buf[len] = '\0';

        // Check for HOME command first
        if (strcmp(buf, "HOME") == 0) {
            returnToHome();
            return;
        }


        // Debug RAW received line
        Serial.print("RAW:'");
        Serial.print(buf);
        Serial.println("'");

        float az, el;

        // ───────────────────────────────────────────────
        //       ROBUST PARSER (ignores whitespace)
        // ───────────────────────────────────────────────
        char *p = buf;

        // skip leading whitespace
        while (*p == ' ' || *p == '\t' || *p == '\r') p++;

        char *tok = strtok(p, ",");
        if (!tok) {
            Serial.println("ERR parse: no az");
            return;
        }
        az = atof(tok);

        tok = strtok(NULL, ",");
        if (!tok) {
            Serial.println("ERR parse: no el");
            return;
        }
        el = atof(tok);

        // ───────────────────────────
        //    Angle post-processing
        // ───────────────────────────
        while (az < 0) az += 360.0;
        while (az >= 360) az -= 360.0;

        el = constrain(el, EL_MIN_DEG, EL_MAX_DEG);

        // ───────────────────────────
        //    Az shortest-path logic
        // ───────────────────────────
        
        long currentAzSteps = azStepper.currentPosition();
        
        //Normalise current position to 0–3199
        // currentPosition() can grow indefinitely (e.g. 6400 after two full rotations)
        currentAzSteps = (currentAzSteps % (long)MAX_AZ_STEPS + (long)MAX_AZ_STEPS)
                          % (long)MAX_AZ_STEPS;
        // The double modulo handles negative numbers:
         // e.g. -100 % 3200 = -100 in C++ (not 3100)
         // (-100 + 3200) % 3200 = 3100 


        // Convert target angle to steps
        long targetAzSteps = (long)(az * STEPS_PER_DEG);
        // e.g. 270° * 8.888 = 2399 steps

        long diff = targetAzSteps - currentAzSteps;
        // e.g. current=2399 (270°), target=177 (20°)
        // diff = 177 - 2399 = -2222 steps = -250° (go CCW 250°)

        if (diff >  (long)(180.0 * STEPS_PER_DEG)) diff -= (long)MAX_AZ_STEPS; 
        // e.g. +2978 -> -222 (go CCW 25° instead of CW 335°)
        if (diff < -(long)(180.0 * STEPS_PER_DEG)) diff += (long)MAX_AZ_STEPS;
        
       // Using actual position (not normalised) preserves the absolute step counter
        azStepper.moveTo(azStepper.currentPosition() + diff);

        // For now, ignore EL (hardware not ready)
        elStepper.moveTo((long)(el * STEPS_PER_DEG));

        Serial.print("OK az="); Serial.print(az);
        Serial.print(" el=");   Serial.print(el);
        Serial.print(" azSteps="); Serial.println(azStepper.targetPosition());
    }

    azStepper.run();
    elStepper.run();  
}


void returnToHome() {
    // Directly move to step 0 - no shortest path calculation //no limit switch
    // Use current actual step count to determine direction
    long azPos = azStepper.currentPosition();
    long elPos = elStepper.currentPosition();
    
    // For EL — always direct, no wrap issue (0-90° only, no full rotation)
    elStepper.moveTo(0);
    
    // For AZ — take actual shortest physical path back to 0
    // currentPosition could be e.g. 3111 steps (350°) or -500 steps
    // Normalise to find true shortest return
    long fullRev = (long)MAX_AZ_STEPS;
    long pos = ((azPos % fullRev) + fullRev) % fullRev;  // 0 to 3199
    
    if (pos <= fullRev/2) {
        // less than 180° from home — go back directly
        azStepper.moveTo(azPos - pos);
    } else {
        // more than 180° from home — go forward to next home
        azStepper.moveTo(azPos + (fullRev - pos));
    }
    
    // Wait until both reach home
    while (azStepper.distanceToGo() != 0 || elStepper.distanceToGo() != 0) {
        azStepper.run();
        elStepper.run();
    }
    
    // Reset counters to true zero
    azStepper.setCurrentPosition(0);
    elStepper.setCurrentPosition(0);
    Serial.println("[Tracker] Homed.");
}
