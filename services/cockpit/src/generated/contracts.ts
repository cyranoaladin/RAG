// Generated from packages/contracts/schema. Do not edit manually.

export type ContractBundle =
  | RetrievalRequest
  | RetrievalResponse
  | SearchPayload
  | ChatPayload
  | ChatRequest
  | ChatResponse
  | InternalIdentity
  | InternalIdentityEnvelope
  | PilotRetrievalScopeArtifact
  | ReviewQueuePayload
  | ReviewDecisionPayload
  | ReviewDecisionRequest
  | ReviewQueueResponse
  | ReviewDecisionResponse
  | CollectionProfile
  | SearchPlan
  | ResourceCandidate
  | ArtifactRecord
  | RoutingDecision
  | QualityReport
  | IngestionRun
  | CoverageSnapshot;
export type TypeDoc =
  | 'programme_officiel'
  | 'ressource_officielle'
  | 'cours'
  | 'fiche_synthese'
  | 'fiche_methode'
  | 'td'
  | 'tp'
  | 'exercice'
  | 'exercice_corrige'
  | 'devoir'
  | 'devoir_corrige'
  | 'evaluation'
  | 'evaluation_corrigee'
  | 'bac_blanc'
  | 'brevet_blanc'
  | 'annale'
  | 'sujet_zero'
  | 'corrige'
  | 'bareme'
  | 'grille_evaluation'
  | 'grille_grand_oral'
  | 'oral'
  | 'diaporama'
  | 'latex'
  | 'notebook'
  | 'code'
  | 'image'
  | 'scan'
  | 'copie'
  | 'rapport'
  | 'referentiel'
  | 'modalite_examen'
  | 'autre';
export type DesiredDocTypes = TypeDoc[];
export type DifficultyMax = number | null;
export type Intent = 'remediation' | 'revision' | 'exercise' | 'program' | 'exam_prep' | 'context';
export type Notions = string[];
export type Query = string;
export type Hybrid = boolean;
export type IncludeCitations = boolean;
export type K = number;
export type Rerank = boolean;
export type Candidat = 'scolarise' | 'individuel' | 'libre' | 'cned_reglemente' | 'cned_libre' | 'aefe' | 'both';
export type CandidateStatusRef = string | null;
export type Establishment = string | null;
/**
 * @minItems 1
 */
export type Matieres = [string, ...string[]];
export type Needs = string[];
export type NexusGroupId = string | null;
export type NexusOffer = string | null;
export type Niveau =
  'troisieme' | 'seconde' | 'premiere' | 'terminale' | 'cycle4' | 'lycee_gt' | 'voie_generale' | 'voie_technologique';
export type Objective = string | null;
export type OfficialLevelRef = string | null;
export type Options = string[];
export type RiskLevel = ('low' | 'medium' | 'high' | 'critical') | null;
export type SchoolCalendarZone = string | null;
export type SchoolYear = string;
export type Specialites = string[];
export type StatusDetail =
  | 'aefe'
  | 'systeme_francais_hors_aefe'
  | 'systeme_tunisien'
  | 'double_cursus'
  | 'candidat_libre'
  | 'cned_reglemente'
  | 'cned_libre'
  | 'unknown';
export type StatutEnseignement =
  | 'tronc_commun'
  | 'enseignement_commun'
  | 'specialite'
  | 'eds'
  | 'option'
  | 'maths_complementaires'
  | 'maths_expertes'
  | 'snt'
  | 'enseignement_scientifique'
  | 'emc'
  | 'atelier'
  | 'stage'
  | 'remediation'
  | 'examen'
  | 'unknown';
export type StudentId = string | null;
export type TargetPathway = string | null;
export type TeacherConfirmed = boolean;
export type Voie = 'college' | 'generale' | 'technologique' | 'professionnelle' | 'aefe' | 'unknown';
export type Warnings = string[];
export type Zone = string;
export type ChunkId = string;
export type Page = number | null;
export type Rights = string;
export type SourceLabel = string;
export type SourceUri = string;
export type DocId = string;
export type Excerpt = string;
export type Score = number;
export type Title = string | null;
export type Results = RetrievalResult[];
export type Warnings1 = string[];
/**
 * @minItems 1
 */
export type Collections = [string, ...string[]];
export type K1 = number | null;
export type Query1 = string;
/**
 * @minItems 1
 */
export type Collections1 = [string, ...string[]];
export type History = ChatMessage[] | null;
export type Content = string;
export type Role = 'system' | 'user' | 'assistant';
export type Query2 = string;
export type TopK = number | null;
export type AnswerMaxChars = number;
export type Collections2 = string[];
export type History1 = ChatMessage[];
export type IncludeRetrieval = boolean;
export type Query3 = string;
export type TopK1 = number;
export type Answer = string;
export type ChunkId1 = string;
export type DocId1 = string;
export type Page1 = number | null;
export type Rights1 = string;
export type SourceLabel1 = string;
export type SourceUri1 = string;
export type Citations = ChatCitation[];
export type Grounded = boolean;
export type RefusalReason = string | null;
export type RetrievalHits = RetrievalResult[];
export type Warnings2 = string[];
export type Aud = string;
export type Exp = number;
export type Iss = string;
export type Jti = string;
/**
 * Niveau principal du profil
 */
export type Niveau1 =
  'troisieme' | 'seconde' | 'premiere' | 'terminale' | 'cycle4' | 'lycee_gt' | 'voie_generale' | 'voie_technologique';
/**
 * Audience ciblée
 */
export type Audience = 'libre' | 'aefe' | 'tous';
/**
 * Type de candidat
 */
export type Candidat1 = 'scolarise' | 'individuel' | 'libre' | 'cned_reglemente' | 'cned_libre' | 'aefe' | 'both';
/**
 * Matières suivies
 *
 * @minItems 1
 * @maxItems 16
 */
export type Matieres1 =
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ];
/**
 * Statut pédagogique
 */
export type StatutEnseignement1 =
  | 'tronc_commun'
  | 'enseignement_commun'
  | 'specialite'
  | 'eds'
  | 'option'
  | 'maths_complementaires'
  | 'maths_expertes'
  | 'snt'
  | 'enseignement_scientifique'
  | 'emc'
  | 'atelier'
  | 'stage'
  | 'remediation'
  | 'examen'
  | 'unknown';
/**
 * Parcours de l'élève
 */
export type Voie1 = 'college' | 'generale' | 'technologique' | 'professionnelle' | 'aefe' | 'unknown';
export type Role1 = 'student' | 'teacher' | 'admin' | 'ingest_agent' | 'reviewer';
export type SchoolYear1 = string;
export type Sub = string;
export type Tenant = string;
/**
 * @minItems 1
 * @maxItems 16
 */
export type AllowedCollections =
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ];
export type Aud1 = string;
export type Exp1 = number;
export type Iat = number;
export type Iss1 = string;
export type Jti1 = string;
export type ProtocolVersion = '1';
export type ScopeDigest = string;
export type ScopeId = string;
export type Sub1 = string;
export type ArtifactVersion = '1';
export type Audience1 = 'libre' | 'aefe' | 'tous';
/**
 * @minItems 1
 * @maxItems 16
 */
export type Candidates =
  | [Candidat]
  | [Candidat, Candidat]
  | [Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat]
  | [Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat, Candidat]
  | [
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat
    ]
  | [
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat
    ]
  | [
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat
    ]
  | [
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat
    ]
  | [
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat,
      Candidat
    ];
export type Tenant1 = string;
export type SchoolYear2 = string;
export type ScopeId1 = string;
export type SourceSha256 = string;
export type Status = 'eligible_for_promotion';
/**
 * @minItems 1
 * @maxItems 16
 */
export type Subjects =
  | [PilotScopeSubject]
  | [PilotScopeSubject, PilotScopeSubject]
  | [PilotScopeSubject, PilotScopeSubject, PilotScopeSubject]
  | [PilotScopeSubject, PilotScopeSubject, PilotScopeSubject, PilotScopeSubject]
  | [PilotScopeSubject, PilotScopeSubject, PilotScopeSubject, PilotScopeSubject, PilotScopeSubject]
  | [PilotScopeSubject, PilotScopeSubject, PilotScopeSubject, PilotScopeSubject, PilotScopeSubject, PilotScopeSubject]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ]
  | [
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject,
      PilotScopeSubject
    ];
export type Collection = string;
export type Matiere = string;
export type ProgrammeVersion = string;
export type Collection1 = string | null;
export type Limit = number;
export type Offset = number;
export type Collection2 = string | null;
export type Decision = 'reviewed' | 'quarantined';
export type TargetId = string;
export type TargetType = 'doc' | 'chunk';
export type Collection3 = string | null;
export type Decision1 = 'reviewed' | 'quarantined';
export type TargetId1 = string;
export type TargetType1 = 'doc' | 'chunk';
export type Tenant2 = string;
export type ChunkCount = number;
export type Collection4 = string;
export type DocId2 = string;
export type FirstIndexed = string | null;
export type LastIndexed = string | null;
export type Rights2 = string;
export type SourceKind = string;
export type SourceLabel2 = string;
export type SourceUri2 = string;
export type TypeDoc1 = string;
export type Documents = ReviewQueueDocument[];
export type Offset1 = number;
export type Returned = number;
export type TotalPendingDocs = number;
export type CacheInvalidatedThisWorker = boolean;
export type ChunksAffected = number;
export type Decision2 = 'reviewed' | 'quarantined';
export type MaxStaleOtherWorkersS = 0;
export type TargetId2 = string;
export type TargetType2 = 'doc' | 'chunk';
/**
 * @minItems 1
 */
export type AllowedDomains = [string, ...string[]];
export type ChunkOverlap = number;
export type Enabled = boolean;
export type ExcludedTopics = string[];
/**
 * @minItems 1
 */
export type ExpectedResourceTypes = [TypeDoc, ...TypeDoc[]];
/**
 * @minItems 1
 */
export type ExpectedTopics = [string, ...string[]];
export type Language = string;
export type MaxChunkSize = number;
export type MaxDocumentsPerRun = number;
export type MaxQueriesPerRun = number;
export type MinExtractionQuality = number;
export type MinScopeConfidence = number;
export type MinSourceConfidence = number;
export type Owner = string;
export type ProfileVersion = string;
export type AutoPublish = false;
export type Mode = 'human_review';
export type RejectAmbiguousRouting = boolean;
export type RejectUnknownRights = boolean;
/**
 * @minItems 1
 */
export type Audience2 = [Audience3, ...Audience3[]];
export type Audience3 = 'libre' | 'aefe' | 'tous';
export type Collection5 = string;
export type Matiere1 = string;
export type ProgrammeVersion1 = string;
export type SchoolYear3 = string;
export type Tenant3 = string;
export type Visibility = 'public' | 'internal' | 'restricted' | 'private';
export type SearchCadence = 'daily' | 'weekly' | 'monthly' | 'manual';
export type SeedUrls = string[];
export type SourceAuthority = 'official' | 'authorized' | 'unknown';
export type Title1 = string;
/**
 * @minItems 1
 */
export type AllowedDomains1 = [string, ...string[]];
export type ExcludedTopics1 = string[];
export type GapTargets = string[];
export type GeneratedAt = string;
export type MaxResults = number;
export type ProfileVersion1 = string;
/**
 * @minItems 1
 */
export type Queries = [string, ...string[]];
export type Reason = string;
export type RequiredResourceTypes = TypeDoc[];
export type RequiredTopics = string[];
export type RunId = string;
export type SearchPlanId = string;
export type CandidateId = string;
export type CanonicalUrl = string;
export type DedupKey = string;
export type DiscoveredAt = string;
export type Domain = string;
export type Language1 = string;
export type Publisher = string | null;
export type RelevanceEvidence = string[];
export type ResourceId = string;
export type RunId1 = string;
export type SourceUrl = string;
export type Title2 = string | null;
export type ArtifactId = string;
export type CollectedAt = string;
export type Domain1 = string;
export type ExtractedTextRef = string | null;
export type FinalUrl = string;
export type License = string | null;
export type MimeDeclared = string;
export type MimeDetected = string;
export type OriginalUrl = string;
export type PagesCount = number | null;
export type Publisher1 = string | null;
export type ResourceId1 = string;
export type Rights3 =
  | 'officiel_public'
  | 'public_allowed'
  | 'nexus_proprietaire'
  | 'usage_interne'
  | 'student_private'
  | 'parent_private'
  | 'commercial_confidential'
  | 'restricted'
  | 'unknown';
export type RunId2 = string;
export type Sha256 = string;
export type SizeBytes = number;
export type Title3 = string | null;
export type Version = string | null;
export type AgentIdentity = string;
export type Confidence = number;
export type DecidedAt = string;
export type Decision3 = 'ROUTE' | 'QUARANTINE' | 'REJECT' | 'DUPLICATE' | 'SUPERSEDED';
export type DecisionId = string;
export type Errors = string[];
export type Evidence = string[];
export type ProfileVersion2 = string;
export type ResourceId2 = string;
/**
 * @minItems 1
 */
export type RulesApplied = [string, ...string[]];
export type RunId3 = string;
export type DuplicateDetected = boolean;
export type EvaluatedAt = string;
export type ExtractionQuality = number;
export type LanguageDetected = string;
export type MatiereConformity = boolean;
export type MetadataQuality = number;
export type NiveauConformity = boolean;
export type PiiDetected = boolean;
export type ProgrammeConformity = boolean;
export type Readability = number;
export type RejectionReasons = string[];
export type RelevanceScore = number;
export type ReportId = string;
export type ResourceId3 = string;
export type RunId4 = string;
export type StructureScore = number;
export type TopicCoverage = number;
export type VoieConformity = boolean;
export type CodeVersion = string | null;
export type Errors1 = string[];
export type FinishedAt = string | null;
export type JobsTotal = number;
export type Mode1 = 'auto_stage';
export type ProfileVersion3 = string;
export type ResourcesAccepted = number;
export type ResourcesDiscovered = number;
export type ResourcesFetched = number;
export type ResourcesNeedsReview = number;
export type ResourcesQuarantined = number;
export type ResourcesRejected = number;
export type ResourcesRetrievalEligible = number;
export type RunId5 = string;
export type StartedAt = string | null;
export type Status1 = 'planned' | 'running' | 'succeeded' | 'failed' | 'partial' | 'cancelled';
export type Trigger = 'scheduled' | 'manual';
export type AverageQuality = number | null;
export type CoveredTopics = string[];
/**
 * @minItems 1
 */
export type ExpectedTopics1 = [string, ...string[]];
export type Gaps = string[];
export type InsufficientTopics = string[];
export type PeriodEnd = string;
export type PeriodStart = string;
export type RecommendedNextQueries = string[];
export type SnapshotId = string;
export type StaleResources = number;

export interface RetrievalRequest {
  need: RetrievalNeed;
  retrieval?: RetrievalOptions;
  student_profile: StudentProfile;
}
export interface RetrievalNeed {
  desired_doc_types?: DesiredDocTypes;
  difficulty_max?: DifficultyMax;
  intent: Intent;
  notions?: Notions;
  query: Query;
}
export interface RetrievalOptions {
  hybrid?: Hybrid;
  include_citations?: IncludeCitations;
  k?: K;
  rerank?: Rerank;
}
export interface StudentProfile {
  availability?: Availability;
  candidat: Candidat;
  candidate_status_ref?: CandidateStatusRef;
  establishment?: Establishment;
  matieres: Matieres;
  needs?: Needs;
  nexus_group_id?: NexusGroupId;
  nexus_offer?: NexusOffer;
  niveau: Niveau;
  objective?: Objective;
  official_level_ref?: OfficialLevelRef;
  options?: Options;
  risk_level?: RiskLevel;
  school_calendar_zone?: SchoolCalendarZone;
  school_year: SchoolYear;
  specialites?: Specialites;
  status_detail?: StatusDetail;
  statut_enseignement: StatutEnseignement;
  student_id?: StudentId;
  target_pathway?: TargetPathway;
  teacher_confirmed?: TeacherConfirmed;
  voie: Voie;
  warnings?: Warnings;
  zone: Zone;
}
export interface Availability {
  [k: string]: unknown;
}
export interface RetrievalResponse {
  filters_applied?: FiltersApplied;
  results?: Results;
  warnings?: Warnings1;
}
export interface FiltersApplied {
  [k: string]: unknown;
}
export interface RetrievalResult {
  chunk_id: ChunkId;
  citation?: Citation | null;
  doc_id: DocId;
  excerpt: Excerpt;
  metadata?: Metadata;
  score: Score;
  title?: Title;
}
export interface Citation {
  page?: Page;
  rights: Rights;
  source_label: SourceLabel;
  source_uri: SourceUri;
}
export interface Metadata {
  [k: string]: unknown;
}
/**
 * Browser-to-BFF search input; no identity or server credentials.
 */
export interface SearchPayload {
  collections: Collections;
  k?: K1;
  query: Query1;
}
/**
 * Browser-to-BFF chat input; the BFF alone builds the learner profile.
 */
export interface ChatPayload {
  collections: Collections1;
  history?: History;
  query: Query2;
  top_k?: TopK;
}
export interface ChatMessage {
  content: Content;
  role: Role;
}
export interface ChatRequest {
  answer_max_chars?: AnswerMaxChars;
  collections?: Collections2;
  history?: History1;
  include_retrieval?: IncludeRetrieval;
  query: Query3;
  student_profile: StudentProfile;
  top_k?: TopK1;
}
export interface ChatResponse {
  answer: Answer;
  citations?: Citations;
  grounded?: Grounded;
  refusal_reason?: RefusalReason;
  retrieval_hits?: RetrievalHits;
  warnings?: Warnings2;
}
export interface ChatCitation {
  chunk_id: ChunkId1;
  doc_id: DocId1;
  page?: Page1;
  rights: Rights1;
  source_label: SourceLabel1;
  source_uri: SourceUri1;
}
/**
 * Claims minimaux produits par le cockpit et consommés par rag-engine.
 */
export interface InternalIdentity {
  aud: Aud;
  exp: Exp;
  iss: Iss;
  jti: Jti;
  niveau: Niveau1;
  pedagogical_profile: PedagogicalProfile;
  role: Role1;
  school_year: SchoolYear1;
  sub: Sub;
  tenant: Tenant;
}
/**
 * Sous-ensemble pédagogique fermé, sans identifiant ni champ libre.
 */
export interface PedagogicalProfile {
  audience: Audience;
  candidat: Candidat1;
  matieres: Matieres1;
  statut_enseignement: StatutEnseignement1;
  voie: Voie1;
}
/**
 * Enveloppe signée liant le transport à une identité et à un scope.
 */
export interface InternalIdentityEnvelope {
  allowed_collections: AllowedCollections;
  aud: Aud1;
  exp: Exp1;
  iat: Iat;
  identity: InternalIdentity;
  iss: Iss1;
  jti: Jti1;
  protocol_version: ProtocolVersion;
  scope_digest: ScopeDigest;
  scope_id: ScopeId;
  sub: Sub1;
}
/**
 * Projection adressée par contenu du scope dormant issu de LOT38.
 */
export interface PilotRetrievalScopeArtifact {
  artifact_version: ArtifactVersion;
  identity: PilotScopeIdentity;
  school_year: SchoolYear2;
  scope_id: ScopeId1;
  source_sha256: SourceSha256;
  status: Status;
  subjects: Subjects;
}
/**
 * Projection non personnelle de l'identité autorisée par LOT38.
 */
export interface PilotScopeIdentity {
  audience: Audience1;
  candidates: Candidates;
  niveau: Niveau;
  statut_enseignement: StatutEnseignement;
  tenant: Tenant1;
  voie: Voie;
}
/**
 * Matière, collection et version de programme liées au scope.
 */
export interface PilotScopeSubject {
  collection: Collection;
  matiere: Matiere;
  programme_version: ProgrammeVersion;
}
/**
 * Paramètres navigateur vers BFF pour consulter la file de review.
 */
export interface ReviewQueuePayload {
  collection?: Collection1;
  limit?: Limit;
  offset?: Offset;
}
/**
 * Décision navigateur vers BFF, sans identité ni texte libre.
 */
export interface ReviewDecisionPayload {
  collection?: Collection2;
  decision: Decision;
  target_id: TargetId;
  target_type?: TargetType;
}
/**
 * Décision BFF vers moteur enrichie du tenant signé.
 */
export interface ReviewDecisionRequest {
  collection?: Collection3;
  decision: Decision1;
  target_id: TargetId1;
  target_type?: TargetType1;
  tenant: Tenant2;
}
/**
 * Page de documents en attente retournée par le moteur.
 */
export interface ReviewQueueResponse {
  documents: Documents;
  offset: Offset1;
  returned: Returned;
  total_pending_docs: TotalPendingDocs;
}
/**
 * Document en attente exposé par la file de review.
 */
export interface ReviewQueueDocument {
  chunk_count: ChunkCount;
  collection: Collection4;
  doc_id: DocId2;
  first_indexed: FirstIndexed;
  last_indexed: LastIndexed;
  rights: Rights2;
  source_kind: SourceKind;
  source_label: SourceLabel2;
  source_uri: SourceUri2;
  type_doc: TypeDoc1;
}
/**
 * Résultat borné d'une décision de review.
 */
export interface ReviewDecisionResponse {
  cache_invalidated_this_worker: CacheInvalidatedThisWorker;
  chunks_affected: ChunksAffected;
  decision: Decision2;
  max_stale_other_workers_s: MaxStaleOtherWorkersS;
  target_id: TargetId2;
  target_type: TargetType2;
}
/**
 * Profil déclaratif complet d'une collection gouvernée.
 */
export interface CollectionProfile {
  allowed_domains: AllowedDomains;
  chunk_overlap: ChunkOverlap;
  enabled: Enabled;
  excluded_topics?: ExcludedTopics;
  expected_resource_types: ExpectedResourceTypes;
  expected_topics: ExpectedTopics;
  language?: Language;
  max_chunk_size: MaxChunkSize;
  max_documents_per_run: MaxDocumentsPerRun;
  max_queries_per_run: MaxQueriesPerRun;
  min_extraction_quality: MinExtractionQuality;
  min_scope_confidence: MinScopeConfidence;
  min_source_confidence: MinSourceConfidence;
  owner: Owner;
  profile_version: ProfileVersion;
  publication?: PublicationPolicy;
  reject_ambiguous_routing?: RejectAmbiguousRouting;
  reject_unknown_rights?: RejectUnknownRights;
  scope: ResourceScope;
  search_cadence: SearchCadence;
  seed_urls?: SeedUrls;
  source_authority: SourceAuthority;
  title: Title1;
}
/**
 * Politique de publication d'une collection — verrouillée en LOT44a.
 *
 * ``auto_publish`` est typé ``Literal[False]`` : ce n'est pas une valeur
 * par défaut contournable, c'est une garantie structurelle que
 * l'auto-publication ne peut pas être activée par ce contrat tant que le
 * sous-système de publication n'existe pas.
 */
export interface PublicationPolicy {
  auto_publish?: AutoPublish;
  mode?: Mode;
}
/**
 * Scope gouverné complet — obligatoire et fail-closed.
 *
 * Reprend exactement les dix dimensions de scope déjà gouvernées côté
 * rag-engine (colonnes ``rag_chunks`` introduites en LOT41,
 * ``services/rag-engine/infra/postgres/migrations/003_profile_filtering.sql``).
 * Aucun champ n'a de valeur par défaut : un scope incomplet ne peut pas
 * être construit, jamais deviné silencieusement.
 */
export interface ResourceScope {
  audience: Audience2;
  candidat: Candidat;
  collection: Collection5;
  matiere: Matiere1;
  niveau: Niveau;
  programme_version: ProgrammeVersion1;
  school_year: SchoolYear3;
  tenant: Tenant3;
  visibility: Visibility;
  voie: Voie;
}
/**
 * Plan de recherche généré pour une collection, justifié requête par requête.
 */
export interface SearchPlan {
  allowed_domains: AllowedDomains1;
  excluded_topics?: ExcludedTopics1;
  gap_targets?: GapTargets;
  generated_at: GeneratedAt;
  max_results: MaxResults;
  profile_version: ProfileVersion1;
  queries: Queries;
  reason: Reason;
  required_resource_types?: RequiredResourceTypes;
  required_topics?: RequiredTopics;
  run_id: RunId;
  scope: ResourceScope;
  search_plan_id: SearchPlanId;
}
/**
 * Candidat de ressource découvert, toujours rattaché à une ressource.
 *
 * ``resource_id`` est obligatoire : LOT44a crée la ressource provisoire de
 * façon atomique dès l'acceptation du candidat (même transaction), donc
 * aucun ``ResourceCandidate`` ne peut exister sans ressource rattachée.
 * Ce modèle ne porte volontairement pas de champ de statut propre — son
 * état est entièrement représenté par ``resource_state`` (rattaché via
 * ``resource_id``), pour préserver un gate d'état unique.
 */
export interface ResourceCandidate {
  candidate_id: CandidateId;
  canonical_url: CanonicalUrl;
  dedup_key: DedupKey;
  discovered_at: DiscoveredAt;
  domain: Domain;
  language?: Language1;
  proposed_type_doc: TypeDoc;
  publisher?: Publisher;
  relevance_evidence?: RelevanceEvidence;
  resource_id: ResourceId;
  run_id: RunId1;
  scope: ResourceScope;
  source_url: SourceUrl;
  title?: Title2;
}
/**
 * Artefact téléchargé et son empreinte — ancre de déduplication/version.
 */
export interface ArtifactRecord {
  artifact_id: ArtifactId;
  collected_at: CollectedAt;
  domain: Domain1;
  extracted_text_ref?: ExtractedTextRef;
  final_url: FinalUrl;
  license?: License;
  mime_declared: MimeDeclared;
  mime_detected: MimeDetected;
  original_url: OriginalUrl;
  pages_count?: PagesCount;
  publisher?: Publisher1;
  resource_id: ResourceId1;
  rights_status: Rights3;
  run_id: RunId2;
  scope: ResourceScope;
  sha256: Sha256;
  size_bytes: SizeBytes;
  title?: Title3;
  version?: Version;
}
/**
 * Décision de routage — validée côté serveur, jamais devinée.
 */
export interface RoutingDecision {
  agent_identity: AgentIdentity;
  confidence: Confidence;
  decided_at: DecidedAt;
  decision: Decision3;
  decision_id: DecisionId;
  errors?: Errors;
  evidence?: Evidence;
  profile_version: ProfileVersion2;
  resource_id: ResourceId2;
  rules_applied: RulesApplied;
  run_id: RunId3;
  scope: ResourceScope;
}
/**
 * Rapport qualité borné [0, 1] par dimension.
 */
export interface QualityReport {
  duplicate_detected: DuplicateDetected;
  evaluated_at: EvaluatedAt;
  extraction_quality: ExtractionQuality;
  language_detected: LanguageDetected;
  matiere_conformity: MatiereConformity;
  metadata_quality: MetadataQuality;
  niveau_conformity: NiveauConformity;
  pii_detected: PiiDetected;
  programme_conformity: ProgrammeConformity;
  readability: Readability;
  rejection_reasons?: RejectionReasons;
  relevance_score: RelevanceScore;
  report_id: ReportId;
  resource_id: ResourceId3;
  rights_status: Rights3;
  run_id: RunId4;
  scope: ResourceScope;
  structure_score: StructureScore;
  topic_coverage: TopicCoverage;
  voie_conformity: VoieConformity;
}
/**
 * Run d'ingestion — s'arrête à ``resources_retrieval_eligible``.
 *
 * Aucun compteur ``resources_published`` : la publication produit est hors
 * périmètre de LOT44a (cf. ``nexus_contracts.resource_state``).
 */
export interface IngestionRun {
  code_version?: CodeVersion;
  errors?: Errors1;
  finished_at?: FinishedAt;
  jobs_total?: JobsTotal;
  mode?: Mode1;
  profile_version: ProfileVersion3;
  resources_accepted?: ResourcesAccepted;
  resources_discovered?: ResourcesDiscovered;
  resources_fetched?: ResourcesFetched;
  resources_needs_review?: ResourcesNeedsReview;
  resources_quarantined?: ResourcesQuarantined;
  resources_rejected?: ResourcesRejected;
  resources_retrieval_eligible?: ResourcesRetrievalEligible;
  run_id: RunId5;
  scope: ResourceScope;
  started_at?: StartedAt;
  status?: Status1;
  trigger: Trigger;
}
/**
 * Instantané de couverture thématique d'une collection sur une période.
 */
export interface CoverageSnapshot {
  average_quality?: AverageQuality;
  covered_topics?: CoveredTopics;
  expected_topics: ExpectedTopics1;
  gaps?: Gaps;
  insufficient_topics?: InsufficientTopics;
  period_end: PeriodEnd;
  period_start: PeriodStart;
  recommended_next_queries?: RecommendedNextQueries;
  resources_per_topic?: ResourcesPerTopic;
  scope: ResourceScope;
  snapshot_id: SnapshotId;
  stale_resources?: StaleResources;
}
export interface ResourcesPerTopic {
  [k: string]: number;
}
