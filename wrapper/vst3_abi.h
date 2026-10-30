/* The VST3 ABI, hand-written from the published interface definitions for Linux (no COM compatibility: plain big-endian
 * IIDs, tresult kNoInterface = -1, natural struct alignment). Only what wrapper/vst3_wrap.c and tools/vst3_host_test.c use.
 * No Steinberg SDK in this repository. Every interface starts with FUnknown's three slots; an object's first member is its
 * vtable pointer. */
#ifndef MPC_VST3_ABI_H
#define MPC_VST3_ABI_H
#include <stdint.h>

typedef int32_t tresult;
typedef uint8_t TUID[16];
typedef uint16_t char16;
typedef char16 String128[128];
enum { kNoInterface = -1, kResultOk = 0, kResultFalse = 1, kInvalidArgument = 2, kNotImplemented = 3 };
#define IID(a, b, c, d) { (a) >> 24, ((a) >> 16) & 255, ((a) >> 8) & 255, (a) & 255, (b) >> 24, ((b) >> 16) & 255, ((b) >> 8) & 255, (b) & 255, \
                          (c) >> 24, ((c) >> 16) & 255, ((c) >> 8) & 255, (c) & 255, (d) >> 24, ((d) >> 16) & 255, ((d) >> 8) & 255, (d) & 255 }
static const TUID iid_FUnknown = IID(0x00000000u, 0x00000000u, 0xC0000000u, 0x00000046u);
static const TUID iid_IPluginBase = IID(0x22888DDBu, 0x156E45AEu, 0x8358B348u, 0x08190625u);
static const TUID iid_IPluginFactory = IID(0x7A4D811Cu, 0x52114A1Fu, 0xAED9D2EEu, 0x0B43BF9Fu);
static const TUID iid_IPluginFactory2 = IID(0x0007B650u, 0xF24B4C0Bu, 0xA464EDB9u, 0xF00B2ABBu);
static const TUID iid_IComponent = IID(0xE831FF31u, 0xF2D54301u, 0x928EBBEEu, 0x25697802u);
static const TUID iid_IAudioProcessor = IID(0x42043F99u, 0xB7DA453Cu, 0xA569E79Du, 0x9AAEC33Du);
static const TUID iid_IEditController = IID(0xDCD7BBE3u, 0x7742448Du, 0xA874AACCu, 0x979C759Eu);
static const TUID iid_IMidiMapping = IID(0xDF0FF9F7u, 0x49B74669u, 0xB63AB732u, 0x7ADBF5E5u);
static const TUID iid_IProcessContextRequirements = IID(0x2A654303u, 0xEF764E3Du, 0x95B5FE83u, 0x730EF6D0u);

#define FUNKNOWN_SLOTS(T) \
    tresult (*queryInterface)(void *self, const TUID iid, void **obj); \
    uint32_t (*addRef)(void *self); \
    uint32_t (*release)(void *self);
typedef struct { FUNKNOWN_SLOTS(void) } FUnknownVtbl;
typedef struct { const FUnknownVtbl *v; } FUnknown;

typedef struct { char vendor[64], url[256], email[128]; int32_t flags; } PFactoryInfo;
typedef struct { TUID cid; int32_t cardinality; char category[32], name[64]; } PClassInfo;
typedef struct {
    TUID cid; int32_t cardinality; char category[32], name[64];
    uint32_t classFlags; char subCategories[128], vendor[64], version[64], sdkVersion[64];
} PClassInfo2;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*getFactoryInfo)(void *self, PFactoryInfo *info);
    int32_t (*countClasses)(void *self);
    tresult (*getClassInfo)(void *self, int32_t index, PClassInfo *info);
    tresult (*createInstance)(void *self, const char *cid, const char *iid, void **obj);
    tresult (*getClassInfo2)(void *self, int32_t index, PClassInfo2 *info);
} FactoryVtbl;

typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*read)(void *self, void *buffer, int32_t n, int32_t *done);
    tresult (*write)(void *self, void *buffer, int32_t n, int32_t *done);
    tresult (*seek)(void *self, int64_t pos, int32_t mode, int64_t *result);
    tresult (*tell)(void *self, int64_t *pos);
} IBStreamVtbl;
typedef struct { const IBStreamVtbl *v; } IBStream;

typedef struct { int32_t mediaType, direction, channelCount; String128 name; int32_t busType; uint32_t flags; } BusInfo;
typedef struct { int32_t mediaType, busIndex, channel; } RoutingInfo;
enum { kAudio = 0, kEvent = 1, kInput = 0, kOutput = 1, kMain = 0, kDefaultActive = 1 };

typedef struct { int32_t processMode, symbolicSampleSize, maxSamplesPerBlock; double sampleRate; } ProcessSetup;
typedef struct { int32_t numChannels; uint64_t silenceFlags; float **channelBuffers32; } AudioBusBuffers;
typedef struct {
    uint32_t state; double sampleRate; int64_t projectTimeSamples, systemTime, continousTimeSamples;
    double projectTimeMusic, barPositionMusic, cycleStartMusic, cycleEndMusic, tempo;
    int32_t timeSigNumerator, timeSigDenominator;
    struct { uint8_t keyNote, rootNote; int16_t chordMask; } chord;
    int32_t smpteOffsetSubframes;
    struct { uint32_t framesPerSecond, flags; } frameRate;
    int32_t samplesToNextClock;
} ProcessContext;
enum { kPlaying = 1 << 1, kProjectTimeMusicValid = 1 << 9, kTempoValid = 1 << 10 };

typedef struct {
    FUNKNOWN_SLOTS(void)
    uint32_t (*getParameterId)(void *self);
    int32_t (*getPointCount)(void *self);
    tresult (*getPoint)(void *self, int32_t index, int32_t *offset, double *value);
    tresult (*addPoint)(void *self, int32_t offset, double value, int32_t *index);
} IParamValueQueueVtbl;
typedef struct { const IParamValueQueueVtbl *v; } IParamValueQueue;
typedef struct {
    FUNKNOWN_SLOTS(void)
    int32_t (*getParameterCount)(void *self);
    IParamValueQueue *(*getParameterData)(void *self, int32_t index);
    IParamValueQueue *(*addParameterData)(void *self, const uint32_t *id, int32_t *index);
} IParameterChangesVtbl;
typedef struct { const IParameterChangesVtbl *v; } IParameterChanges;

typedef struct {
    int32_t busIndex, sampleOffset; double ppqPosition; uint16_t flags, type;
    union {
        struct { int16_t channel, pitch; float tuning, velocity; int32_t length, noteId; } noteOn;
        struct { int16_t channel, pitch; float velocity; int32_t noteId; float tuning; } noteOff;
        struct { uint32_t size, type; const uint8_t *bytes; } data;
        struct { int16_t channel, pitch; float pressure; int32_t noteId; } polyPressure;
        struct { uint32_t typeId; int32_t noteId; uint32_t textLen; const char16 *text; } noteExpressionText;
    };
} Event;
enum { kNoteOnEvent = 0, kNoteOffEvent = 1, kPolyPressureEvent = 3 };
typedef struct {
    FUNKNOWN_SLOTS(void)
    int32_t (*getEventCount)(void *self);
    tresult (*getEvent)(void *self, int32_t index, Event *e);
    tresult (*addEvent)(void *self, Event *e);
} IEventListVtbl;
typedef struct { const IEventListVtbl *v; } IEventList;

typedef struct {
    int32_t processMode, symbolicSampleSize, numSamples, numInputs, numOutputs;
    AudioBusBuffers *inputs, *outputs;
    IParameterChanges *inputParameterChanges, *outputParameterChanges;
    IEventList *inputEvents, *outputEvents;
    ProcessContext *processContext;
} ProcessData;

typedef struct {
    uint32_t id; String128 title, shortTitle, units; int32_t stepCount; double defaultNormalizedValue;
    int32_t unitId, flags;
} ParameterInfo;
enum { kCanAutomate = 1, kIsReadOnly = 2, kIsList = 8, kIsHidden = 16, kIsProgramChange = 1 << 15, kIsBypass = 1 << 16 };

typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*beginEdit)(void *self, uint32_t id);
    tresult (*performEdit)(void *self, uint32_t id, double value);
    tresult (*endEdit)(void *self, uint32_t id);
    tresult (*restartComponent)(void *self, int32_t flags);
} IComponentHandlerVtbl;
typedef struct { const IComponentHandlerVtbl *v; } IComponentHandler;

typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*initialize)(void *self, FUnknown *context);
    tresult (*terminate)(void *self);
    tresult (*getControllerClassId)(void *self, TUID cid);
    tresult (*setIoMode)(void *self, int32_t mode);
    int32_t (*getBusCount)(void *self, int32_t type, int32_t dir);
    tresult (*getBusInfo)(void *self, int32_t type, int32_t dir, int32_t index, BusInfo *bus);
    tresult (*getRoutingInfo)(void *self, RoutingInfo *in, RoutingInfo *out);
    tresult (*activateBus)(void *self, int32_t type, int32_t dir, int32_t index, uint8_t state);
    tresult (*setActive)(void *self, uint8_t state);
    tresult (*setState)(void *self, IBStream *state);
    tresult (*getState)(void *self, IBStream *state);
} ComponentVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*setBusArrangements)(void *self, uint64_t *inputs, int32_t numIns, uint64_t *outputs, int32_t numOuts);
    tresult (*getBusArrangement)(void *self, int32_t dir, int32_t index, uint64_t *arr);
    tresult (*canProcessSampleSize)(void *self, int32_t size);
    uint32_t (*getLatencySamples)(void *self);
    tresult (*setupProcessing)(void *self, ProcessSetup *setup);
    tresult (*setProcessing)(void *self, uint8_t state);
    tresult (*process)(void *self, ProcessData *data);
    uint32_t (*getTailSamples)(void *self);
} ProcessorVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*initialize)(void *self, FUnknown *context);
    tresult (*terminate)(void *self);
    tresult (*setComponentState)(void *self, IBStream *state);
    tresult (*setState)(void *self, IBStream *state);
    tresult (*getState)(void *self, IBStream *state);
    int32_t (*getParameterCount)(void *self);
    tresult (*getParameterInfo)(void *self, int32_t index, ParameterInfo *info);
    tresult (*getParamStringByValue)(void *self, uint32_t id, double value, char16 *string);
    tresult (*getParamValueByString)(void *self, uint32_t id, char16 *string, double *value);
    double (*normalizedParamToPlain)(void *self, uint32_t id, double value);
    double (*plainParamToNormalized)(void *self, uint32_t id, double value);
    double (*getParamNormalized)(void *self, uint32_t id);
    tresult (*setParamNormalized)(void *self, uint32_t id, double value);
    tresult (*setComponentHandler)(void *self, IComponentHandler *handler);
    void *(*createView)(void *self, const char *name);
} ControllerVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*getMidiControllerAssignment)(void *self, int32_t bus, int16_t channel, int16_t ctrl, uint32_t *id);
} MidiMappingVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    uint32_t (*getProcessContextRequirements)(void *self);
} CtxReqVtbl;

/* ---- editor (IPlugView on X11) ---- */
static const TUID iid_IPlugView = IID(0x5BC32507u, 0xD06049EAu, 0xA6151B52u, 0x2B755B29u);
static const TUID iid_IPlugFrame = IID(0x367FAF01u, 0xAFA94693u, 0x8D4DA2A0u, 0xED0882A3u);
static const TUID iid_IEventHandler = IID(0x561E65C9u, 0x13A0496Fu, 0x813A2C35u, 0x654D7983u);
static const TUID iid_ITimerHandler = IID(0x10BDD94Fu, 0x41424774u, 0x821FAD8Fu, 0xECA72CA9u);
static const TUID iid_IRunLoop = IID(0x18C35366u, 0x97764F1Au, 0x9C5B8385u, 0x7A871389u);
typedef struct { int32_t left, top, right, bottom; } ViewRect;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*isPlatformTypeSupported)(void *self, const char *type);
    tresult (*attached)(void *self, void *parent, const char *type);
    tresult (*removed)(void *self);
    tresult (*onWheel)(void *self, float distance);
    tresult (*onKeyDown)(void *self, char16 key, int16_t keyCode, int16_t modifiers);
    tresult (*onKeyUp)(void *self, char16 key, int16_t keyCode, int16_t modifiers);
    tresult (*getSize)(void *self, ViewRect *size);
    tresult (*onSize)(void *self, ViewRect *size);
    tresult (*onFocus)(void *self, uint8_t state);
    tresult (*setFrame)(void *self, void *frame);
    tresult (*canResize)(void *self);
    tresult (*checkSizeConstraint)(void *self, ViewRect *rect);
} PlugViewVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*resizeView)(void *self, void *view, ViewRect *size);
} PlugFrameVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    void (*onFDIsSet)(void *self, int fd);
} EventHandlerVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    void (*onTimer)(void *self);
} TimerHandlerVtbl;
typedef struct {
    FUNKNOWN_SLOTS(void)
    tresult (*registerEventHandler)(void *self, void *handler, int fd);
    tresult (*unregisterEventHandler)(void *self, void *handler);
    tresult (*registerTimer)(void *self, void *handler, uint64_t ms);
    tresult (*unregisterTimer)(void *self, void *handler);
} RunLoopVtbl;

/* Sizes and offsets on 64-bit Linux, checked against the SDK's own headers (2026-10-30, VST 3.8): a typo above fails the build. */
#if UINTPTR_MAX == 0xFFFFFFFFFFFFFFFFu
#include <stddef.h>
_Static_assert(sizeof(PClassInfo2) == 440 && offsetof(PClassInfo2, sdkVersion) == 376, "PClassInfo2");
_Static_assert(sizeof(BusInfo) == 276 && offsetof(BusInfo, busType) == 268, "BusInfo");
_Static_assert(sizeof(ProcessContext) == 112 && offsetof(ProcessContext, tempo) == 72, "ProcessContext");
_Static_assert(sizeof(Event) == 48 && offsetof(Event, noteOn) == 24, "Event");
_Static_assert(sizeof(ProcessData) == 80 && offsetof(ProcessData, processContext) == 72, "ProcessData");
_Static_assert(sizeof(ParameterInfo) == 792 && offsetof(ParameterInfo, flags) == 788, "ParameterInfo");
_Static_assert(sizeof(AudioBusBuffers) == 24 && sizeof(PFactoryInfo) == 452 && sizeof(PClassInfo) == 116, "small structs");
#endif
#endif
