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
  | RetrievalScopeArtifactV2
  | ReviewQueuePayload
  | ReviewDecisionPayload
  | ReviewDecisionRequest
  | ReviewQueueResponse
  | ReviewDecisionResponse;
export type Matiere = string;
export type Niveau =
  | 'quatrieme'
  | 'troisieme'
  | 'seconde'
  | 'premiere'
  | 'terminale'
  | 'cycle4'
  | 'lycee_gt'
  | 'voie_generale'
  | 'voie_technologique';
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
export type Voie = 'college' | 'generale' | 'technologique' | 'professionnelle' | 'aefe' | 'unknown';
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
export type StudentId = string | null;
export type TargetPathway = string | null;
export type TeacherConfirmed = boolean;
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
  | 'quatrieme'
  | 'troisieme'
  | 'seconde'
  | 'premiere'
  | 'terminale'
  | 'cycle4'
  | 'lycee_gt'
  | 'voie_generale'
  | 'voie_technologique';
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
export type Matiere1 = string;
export type ProgrammeVersion = string;
export type ArtifactVersion1 = '2';
/**
 * @minItems 1
 * @maxItems 3
 */
export type Audiences =
  | ['libre' | 'aefe' | 'tous']
  | ['libre' | 'aefe' | 'tous', 'libre' | 'aefe' | 'tous']
  | ['libre' | 'aefe' | 'tous', 'libre' | 'aefe' | 'tous', 'libre' | 'aefe' | 'tous'];
export type Collection1 = string;
export type Matiere2 = string;
export type ProgrammeVersion1 = string;
/**
 * @minItems 1
 * @maxItems 16
 */
export type Rights2 =
  | [Rights3]
  | [Rights3, Rights3]
  | [Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3, Rights3]
  | [
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3
    ]
  | [
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3
    ]
  | [
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3
    ]
  | [
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3,
      Rights3
    ];
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
export type SchoolYear3 = string;
export type Tenant2 = string;
export type Visibility = 'public' | 'internal' | 'restricted' | 'private';
export type ScopeId2 = string;
export type SourceSha2561 = string;
export type Status1 = 'eligible_for_promotion';
export type Audience2 = 'libre' | 'aefe' | 'tous';
/**
 * @minItems 1
 * @maxItems 16
 */
export type Candidates1 =
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
export type Matiere3 = string;
export type Tenant3 = string;
export type Collection2 = string | null;
export type Limit = number;
export type Offset = number;
export type Collection3 = string | null;
export type Decision = 'reviewed' | 'quarantined';
export type TargetId = string;
export type TargetType = 'doc' | 'chunk';
export type Collection4 = string | null;
export type Decision1 = 'reviewed' | 'quarantined';
export type TargetId1 = string;
export type TargetType1 = 'doc' | 'chunk';
export type Tenant4 = string;
export type ChunkCount = number;
export type Collection5 = string;
export type DocId2 = string;
export type FirstIndexed = string | null;
export type LastIndexed = string | null;
export type Rights4 = string;
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

export interface RetrievalRequest {
  curriculum_scope?: RetrievalCurriculumScope | null;
  need: RetrievalNeed;
  retrieval?: RetrievalOptions;
  student_profile: StudentProfile;
}
/**
 * Portée de la preuve pédagogique, distincte de la cible élève.
 */
export interface RetrievalCurriculumScope {
  matiere: Matiere;
  niveau: Niveau;
  statut_enseignement: StatutEnseignement;
  voie: Voie;
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
  matiere: Matiere1;
  programme_version: ProgrammeVersion;
}
/**
 * Scope étroit séparant identité cible et preuve pédagogique.
 */
export interface RetrievalScopeArtifactV2 {
  artifact_version: ArtifactVersion1;
  evidence_subject: RetrievalScopeEvidenceSubject;
  scope_id: ScopeId2;
  source_sha256: SourceSha2561;
  status: Status1;
  target_identity: RetrievalScopeTargetIdentity;
}
/**
 * Dimensions SQL autoritatives de la preuve curriculaire V2.
 */
export interface RetrievalScopeEvidenceSubject {
  audiences: Audiences;
  candidat: Candidat;
  collection: Collection1;
  matiere: Matiere2;
  niveau: Niveau;
  programme_version: ProgrammeVersion1;
  rights: Rights2;
  school_year: SchoolYear3;
  statut_enseignement: StatutEnseignement;
  tenant: Tenant2;
  visibility: Visibility;
  voie: Voie;
}
/**
 * Cible élève exacte portée par un scope de retrieval V2.
 */
export interface RetrievalScopeTargetIdentity {
  audience: Audience2;
  candidates: Candidates1;
  matiere: Matiere3;
  niveau: Niveau;
  statut_enseignement: StatutEnseignement;
  tenant: Tenant3;
  voie: Voie;
}
/**
 * Paramètres navigateur vers BFF pour consulter la file de review.
 */
export interface ReviewQueuePayload {
  collection?: Collection2;
  limit?: Limit;
  offset?: Offset;
}
/**
 * Décision navigateur vers BFF, sans identité ni texte libre.
 */
export interface ReviewDecisionPayload {
  collection?: Collection3;
  decision: Decision;
  target_id: TargetId;
  target_type?: TargetType;
}
/**
 * Décision BFF vers moteur enrichie du tenant signé.
 */
export interface ReviewDecisionRequest {
  collection?: Collection4;
  decision: Decision1;
  target_id: TargetId1;
  target_type?: TargetType1;
  tenant: Tenant4;
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
  collection: Collection5;
  doc_id: DocId2;
  first_indexed: FirstIndexed;
  last_indexed: LastIndexed;
  rights: Rights4;
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
